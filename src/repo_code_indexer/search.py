from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

from repo_code_indexer.config import get_settings, normalize_text


STOP_WORDS = {
    "a",
    "as",
    "o",
    "os",
    "de",
    "da",
    "das",
    "do",
    "dos",
    "e",
    "em",
    "na",
    "nas",
    "no",
    "nos",
    "para",
    "por",
    "com",
    "sem",
    "como",
    "eu",
    "me",
    "se",
    "the",
    "an",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "for",
    "where",
    "what",
    "how",
    "does",
    "work",
}

TERM_SYNONYMS = {
    "auth": {
        "auth",
        "authenticate",
        "authentication",
        "authorization",
        "login",
        "token",
        "credential",
        "credentials",
        "session",
        "identity",
        "oauth",
        "jwt",
        "signin",
        "signup",
        "user",
    },
    "autent": {
        "autenticacao",
        "autenticar",
        "autenticado",
        "autenticada",
        "auth",
        "authenticate",
        "authentication",
        "authorization",
        "login",
        "token",
        "credencial",
        "credenciais",
        "sessao",
        "usuario",
    },
    "login": {
        "login",
        "signin",
        "auth",
        "authenticate",
        "authentication",
        "session",
        "token",
        "user",
    },
    "token": {
        "token",
        "jwt",
        "bearer",
        "auth",
        "authentication",
        "credential",
        "secret",
    },
    "senha": {"senha", "password", "secret", "credential", "credentials", "auth"},
    "usuario": {"usuario", "user", "account", "identity", "member", "auth"},
    "permiss": {
        "permission",
        "permissions",
        "role",
        "roles",
        "access",
        "authorization",
        "policy",
    },
}

NON_FILTERABLE_METADATA_KEYS = [
    "file_path",
    "language",
    "symbol_name",
    "symbol_type",
    "path_tokens",
    "start_line",
    "end_line",
    "content",
    "chunk_index",
]

_READY = False
_READY_LOCK = threading.Lock()
_CLIENTS: dict[str, Any] = {}
_CLIENT_LOCK = threading.Lock()
_QUERY_EMBED_CACHE: OrderedDict[tuple[Any, ...], tuple[float, ...]] = OrderedDict()
_QUERY_EMBED_CACHE_LOCK = threading.Lock()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path() -> Path:
    settings = get_settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    return settings.state_dir / "projects.json"


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"projects": {}}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"projects": {}}

    projects = data.get("projects")
    if not isinstance(projects, dict):
        return {"projects": {}}
    return {"projects": projects}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_text(value)).strip("-")
    return slug or "project"


def _project_index_name(project_name: str) -> str:
    settings = get_settings()
    prefix = _slugify(settings.vector_index_prefix)[:20]
    slug = _slugify(project_name)[:28]
    digest = hashlib.sha1(project_name.encode("utf-8")).hexdigest()[:8]
    name = "-".join(part for part in (prefix, slug, digest) if part)
    return name[:63].rstrip("-")


def _vector_key(file_path: str, chunk_index: int) -> str:
    return f"{file_path}#{chunk_index}"


def _get_client():
    settings = get_settings()
    with _CLIENT_LOCK:
        client = _CLIENTS.get(settings.aws_region)
        if client is None:
            client = boto3.client(
                "s3vectors",
                region_name=settings.aws_region,
                config=BotoConfig(
                    retries={"max_attempts": 10, "mode": "adaptive"},
                    read_timeout=120,
                    connect_timeout=10,
                ),
            )
            _CLIENTS[settings.aws_region] = client
        return client


def _list_all_vector_buckets() -> list[dict[str, Any]]:
    client = _get_client()
    buckets: list[dict[str, Any]] = []
    next_token: str | None = None

    while True:
        params: dict[str, Any] = {"maxResults": 100}
        if next_token:
            params["nextToken"] = next_token
        response = client.list_vector_buckets(**params)
        buckets.extend(response.get("vectorBuckets", []))
        next_token = response.get("nextToken")
        if not next_token:
            return buckets


def _bucket_exists(vector_bucket_name: str) -> bool:
    for bucket in _list_all_vector_buckets():
        if bucket.get("vectorBucketName") == vector_bucket_name:
            return True
    return False


def _ensure_vector_bucket() -> None:
    settings = get_settings()
    client = _get_client()
    if _bucket_exists(settings.vector_bucket_name):
        return

    try:
        client.create_vector_bucket(vectorBucketName=settings.vector_bucket_name)
    except client.exceptions.ConflictException:
        return


def _list_indexes(index_prefix: str | None = None) -> list[dict[str, Any]]:
    settings = get_settings()
    client = _get_client()
    indexes: list[dict[str, Any]] = []
    next_token: str | None = None

    while True:
        params: dict[str, Any] = {
            "vectorBucketName": settings.vector_bucket_name,
            "maxResults": 100,
        }
        if next_token:
            params["nextToken"] = next_token
        if index_prefix:
            params["prefix"] = index_prefix
        response = client.list_indexes(**params)
        indexes.extend(response.get("indexes", []))
        next_token = response.get("nextToken")
        if not next_token:
            return indexes


def _index_exists(index_name: str) -> bool:
    return any(
        item.get("indexName") == index_name for item in _list_indexes(index_prefix=index_name)
    )


def _ensure_index(index_name: str) -> None:
    settings = get_settings()
    client = _get_client()
    if _index_exists(index_name):
        return

    try:
        client.create_index(
            vectorBucketName=settings.vector_bucket_name,
            indexName=index_name,
            dataType="float32",
            dimension=settings.embedding_dimensions,
            distanceMetric=settings.vector_distance_metric,
            metadataConfiguration={
                "nonFilterableMetadataKeys": NON_FILTERABLE_METADATA_KEYS,
            },
        )
    except client.exceptions.ConflictException:
        return


def _delete_index_if_exists(index_name: str) -> None:
    settings = get_settings()
    client = _get_client()
    try:
        client.delete_index(
            vectorBucketName=settings.vector_bucket_name,
            indexName=index_name,
        )
    except client.exceptions.NotFoundException:
        return


def _update_project_record(
    project_name: str,
    *,
    project_path: str | None = None,
    last_indexed_at: str | None = None,
    last_indexed_chunk_count: int | None = None,
) -> dict[str, Any] | None:
    state = _load_state()
    current = state["projects"].get(project_name)
    if current is None:
        return None

    updated = dict(current)
    updated["updated_at"] = _utcnow_iso()
    if project_path is not None:
        updated["project_path"] = project_path
    if last_indexed_at is not None:
        updated["last_indexed_at"] = last_indexed_at
    if last_indexed_chunk_count is not None:
        updated["last_indexed_chunk_count"] = last_indexed_chunk_count

    state["projects"][project_name] = updated
    _save_state(state)
    return dict(updated)


def ensure_tables() -> None:
    global _READY

    if _READY:
        return

    with _READY_LOCK:
        if _READY:
            return

        _state_path()
        _ensure_vector_bucket()
        _READY = True


def _tokenize_query(query: str) -> set[str]:
    normalized = normalize_text(query)
    tokens = {
        token
        for token in re.findall(r"[a-z0-9_]{3,}", normalized)
        if token not in STOP_WORDS
    }
    expanded = set(tokens)

    for token in list(tokens):
        if len(token) >= 5:
            expanded.add(token[:5])
        for key, values in TERM_SYNONYMS.items():
            if key in token or token in values:
                expanded.update(values)
                expanded.add(key)

    return expanded


def _lexical_bonus(row: dict[str, Any], query: str) -> float:
    terms = _tokenize_query(query)
    if not terms:
        return 0.0

    file_path = normalize_text(str(row.get("file_path", "")))
    content = normalize_text(str(row.get("content", "")))
    symbol_name = normalize_text(str(row.get("symbol_name", "") or ""))
    path_tokens = normalize_text(str(row.get("path_tokens", "") or ""))
    haystack = "\n".join([file_path, symbol_name, path_tokens, content])

    path_hits = 0
    symbol_hits = 0
    content_hits = 0
    exact_phrase_bonus = 0.0
    normalized_query = normalize_text(query).strip()

    if normalized_query and normalized_query in haystack:
        exact_phrase_bonus = 0.2

    for term in terms:
        if term in file_path or term in path_tokens:
            path_hits += 1
        if term in symbol_name:
            symbol_hits += 1
        if term in haystack:
            content_hits += 1

    return (
        min(path_hits * 0.08, 0.24)
        + min(symbol_hits * 0.12, 0.36)
        + min(content_hits * 0.025, 0.25)
        + exact_phrase_bonus
    )


def _rerank_results(query: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reranked: list[dict[str, Any]] = []
    for row in rows:
        semantic_score = float(row.get("semantic_score", row.get("score", 0.0)))
        lexical_score = _lexical_bonus(row, query)
        final_score = semantic_score + lexical_score
        updated = dict(row)
        updated["semantic_score"] = semantic_score
        updated["lexical_db_score"] = 0.0
        updated["lexical_score"] = lexical_score
        updated["score"] = final_score
        reranked.append(updated)

    reranked.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    return reranked


def _semantic_score(distance_metric: str, distance: float) -> float:
    if distance_metric == "cosine":
        return max(0.0, min(1.0, 1.0 - distance))
    return 1.0 / (1.0 + max(distance, 0.0))


def _query_cache_key(query: str) -> tuple[Any, ...]:
    settings = get_settings()
    compact_query = " ".join(query.split())
    return (
        settings.aws_region,
        settings.embedding_model,
        settings.embedding_dimensions,
        settings.embedding_normalize,
        compact_query,
    )


def _get_query_embedding(query: str) -> list[float]:
    from repo_code_indexer.index_flow import embed_texts

    settings = get_settings()
    cache_size = max(0, settings.query_embedding_cache_size)
    cache_key = _query_cache_key(query)

    if cache_size > 0:
        with _QUERY_EMBED_CACHE_LOCK:
            cached = _QUERY_EMBED_CACHE.get(cache_key)
            if cached is not None:
                _QUERY_EMBED_CACHE.move_to_end(cache_key)
                return list(cached)

    embedding = tuple(embed_texts(settings.embedding_model, [query])[0])
    if cache_size <= 0:
        return list(embedding)

    with _QUERY_EMBED_CACHE_LOCK:
        _QUERY_EMBED_CACHE[cache_key] = embedding
        _QUERY_EMBED_CACHE.move_to_end(cache_key)
        while len(_QUERY_EMBED_CACHE) > cache_size:
            _QUERY_EMBED_CACHE.popitem(last=False)

    return list(embedding)


def list_registered_projects() -> list[dict[str, Any]]:
    ensure_tables()
    projects = _load_state()["projects"].values()
    return sorted(
        (dict(project) for project in projects),
        key=lambda item: str(item.get("name", "")).lower(),
    )


def get_registered_project(project_name: str) -> dict[str, Any] | None:
    ensure_tables()
    project = _load_state()["projects"].get(project_name)
    return dict(project) if project is not None else None


def upsert_registered_project(project_name: str, project_path: str) -> dict[str, Any]:
    ensure_tables()
    state = _load_state()
    now = _utcnow_iso()
    existing = state["projects"].get(project_name)
    project = {
        "name": project_name,
        "project_path": project_path,
        "index_name": _project_index_name(project_name),
        "created_at": existing.get("created_at", now) if existing else now,
        "updated_at": now,
        "last_indexed_at": existing.get("last_indexed_at") if existing else None,
        "last_indexed_chunk_count": int(
            existing.get("last_indexed_chunk_count", 0) if existing else 0
        ),
    }
    state["projects"][project_name] = project
    _save_state(state)
    return dict(project)


def delete_registered_project(project_name: str) -> bool:
    ensure_tables()
    state = _load_state()
    if project_name not in state["projects"]:
        return False
    del state["projects"][project_name]
    _save_state(state)
    return True


def delete_project_chunks(project_name: str) -> int:
    ensure_tables()
    _delete_index_if_exists(_project_index_name(project_name))
    return 0


def _put_vectors_batch(index_name: str, vectors: list[dict[str, Any]], attempt: int = 0) -> None:
    settings = get_settings()
    client = _get_client()
    try:
        client.put_vectors(
            vectorBucketName=settings.vector_bucket_name,
            indexName=index_name,
            vectors=vectors,
        )
    except (
        client.exceptions.ServiceUnavailableException,
        client.exceptions.TooManyRequestsException,
    ):
        if len(vectors) > 1:
            midpoint = len(vectors) // 2
            _put_vectors_batch(index_name, vectors[:midpoint], attempt=0)
            _put_vectors_batch(index_name, vectors[midpoint:], attempt=0)
            return
        if attempt >= 4:
            raise
        time.sleep(min(2**attempt, 8))
        _put_vectors_batch(index_name, vectors, attempt=attempt + 1)


def replace_project_chunks(
    project_name: str,
    rows: list[
        tuple[
            str,
            int,
            str,
            str | None,
            str | None,
            str,
            str,
            int,
            int,
            str,
            list[float],
        ]
    ],
) -> int:
    ensure_tables()
    project = get_registered_project(project_name)
    if project is None:
        raise ValueError(f"Projeto nao registrado: {project_name}")

    settings = get_settings()
    index_name = str(project["index_name"])
    _delete_index_if_exists(index_name)
    _ensure_index(index_name)

    vectors: list[dict[str, Any]] = []
    for (
        file_path,
        chunk_index,
        language,
        symbol_name,
        symbol_type,
        path_tokens,
        _search_text,
        start_line,
        end_line,
        content,
        embedding,
    ) in rows:
        vectors.append(
            {
                "key": _vector_key(file_path, chunk_index),
                "data": {"float32": [float(value) for value in embedding]},
                "metadata": {
                    "file_path": file_path,
                    "language": language,
                    "symbol_name": symbol_name or "",
                    "symbol_type": symbol_type or "",
                    "path_tokens": path_tokens or "",
                    "start_line": int(start_line),
                    "end_line": int(end_line),
                    "content": content,
                    "chunk_index": int(chunk_index),
                },
            }
        )

    batch_size = max(1, settings.vector_put_batch_size)
    for start in range(0, len(vectors), batch_size):
        _put_vectors_batch(index_name, vectors[start : start + batch_size])

    _update_project_record(
        project_name,
        last_indexed_at=_utcnow_iso(),
        last_indexed_chunk_count=len(rows),
    )
    return len(rows)


def insert_chunks(
    project_name: str,
    rows: list[
        tuple[
            str,
            int,
            str,
            str | None,
            str | None,
            str,
            str,
            int,
            int,
            str,
            list[float],
        ]
    ],
) -> int:
    return replace_project_chunks(project_name, rows)


def search_code(
    project_name: str,
    query: str,
    limit: int = 5,
    min_score: float | None = None,
) -> dict[str, Any]:
    ensure_tables()
    settings = get_settings()
    project = get_registered_project(project_name)
    if project is None:
        return {
            "results": [],
            "used_fallback": False,
            "applied_min_score": settings.query_min_score,
        }

    query_vector = _get_query_embedding(query)
    effective_min_score = settings.query_min_score if min_score is None else min_score
    candidate_limit = min(max(limit * settings.query_candidate_multiplier, limit), 100)

    try:
        response = _get_client().query_vectors(
            vectorBucketName=settings.vector_bucket_name,
            indexName=str(project["index_name"]),
            queryVector={"float32": query_vector},
            topK=candidate_limit,
            returnDistance=True,
            returnMetadata=True,
        )
    except _get_client().exceptions.NotFoundException:
        return {
            "results": [],
            "used_fallback": False,
            "applied_min_score": effective_min_score,
        }

    distance_metric = str(response.get("distanceMetric", settings.vector_distance_metric))
    rows: list[dict[str, Any]] = []
    for item in response.get("vectors", []):
        metadata = item.get("metadata") or {}
        distance = float(item.get("distance", 1.0))
        row = {
            "file_path": str(metadata.get("file_path", "")),
            "chunk_index": int(metadata.get("chunk_index", 0)),
            "language": str(metadata.get("language", "") or "text"),
            "symbol_name": metadata.get("symbol_name") or None,
            "symbol_type": metadata.get("symbol_type") or None,
            "path_tokens": str(metadata.get("path_tokens", "") or ""),
            "start_line": int(metadata.get("start_line", 0) or 0),
            "end_line": int(metadata.get("end_line", 0) or 0),
            "content": str(metadata.get("content", "")),
            "distance": distance,
            "semantic_score": _semantic_score(distance_metric, distance),
            "score": _semantic_score(distance_metric, distance),
        }
        rows.append(row)

    reranked = _rerank_results(query, rows)
    filtered = [
        row for row in reranked if float(row.get("score", 0.0)) >= effective_min_score
    ]

    if filtered:
        return {
            "results": filtered[:limit],
            "used_fallback": False,
            "applied_min_score": effective_min_score,
        }

    fallback_min_score = min(settings.query_fallback_min_score, effective_min_score)
    fallback_results = [
        row
        for row in reranked
        if float(row.get("score", 0.0)) >= fallback_min_score
        and (
            float(row.get("lexical_score", 0.0)) > 0.0
            or float(row.get("semantic_score", 0.0)) >= fallback_min_score
        )
    ]

    return {
        "results": fallback_results[:limit],
        "used_fallback": bool(fallback_results),
        "applied_min_score": fallback_min_score
        if fallback_results
        else effective_min_score,
    }
