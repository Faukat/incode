from __future__ import annotations

import re
import threading
from typing import Any

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

_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()


def _search_document_sql() -> str:
    return (
        "coalesce(search_text, coalesce(file_path, '') || ' ' || coalesce(content, ''))"
    )


def get_connection():
    import psycopg
    from pgvector.psycopg import register_vector
    from psycopg.rows import dict_row

    settings = get_settings()
    conn = psycopg.connect(settings.postgres_dsn, row_factory=dict_row)
    register_vector(conn)
    return conn


def ensure_tables() -> None:
    global _SCHEMA_READY

    if _SCHEMA_READY:
        return

    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return

        search_document = _search_document_sql()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS registered_projects (
                        name TEXT PRIMARY KEY,
                        project_path TEXT NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW(),
                        last_indexed_at TIMESTAMPTZ,
                        last_indexed_chunk_count INTEGER DEFAULT 0
                    );
                    """
                )
                cur.execute(
                    """
                CREATE TABLE IF NOT EXISTS code_chunks (
                    id BIGSERIAL PRIMARY KEY,
                    project_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                        language TEXT,
                        symbol_name TEXT,
                    symbol_type TEXT,
                    path_tokens TEXT,
                    search_text TEXT,
                    search_vector TSVECTOR,
                    start_line INTEGER,
                    end_line INTEGER,
                    content TEXT NOT NULL,
                    embedding VECTOR(384) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                    );
                    """
                )
                cur.execute(
                    "ALTER TABLE code_chunks ADD COLUMN IF NOT EXISTS symbol_name TEXT;"
                )
                cur.execute(
                    "ALTER TABLE code_chunks ADD COLUMN IF NOT EXISTS symbol_type TEXT;"
                )
                cur.execute(
                    "ALTER TABLE code_chunks ADD COLUMN IF NOT EXISTS path_tokens TEXT;"
                )
                cur.execute(
                    "ALTER TABLE code_chunks ADD COLUMN IF NOT EXISTS search_text TEXT;"
                )
                cur.execute(
                    "ALTER TABLE code_chunks ADD COLUMN IF NOT EXISTS search_vector TSVECTOR;"
                )
                cur.execute(
                    "ALTER TABLE code_chunks ADD COLUMN IF NOT EXISTS start_line INTEGER;"
                )
                cur.execute(
                    "ALTER TABLE code_chunks ADD COLUMN IF NOT EXISTS end_line INTEGER;"
                )
                cur.execute(
                    """
                    UPDATE code_chunks
                    SET
                        search_text = coalesce(search_text, file_path || E'\n' || content),
                        search_vector = to_tsvector(
                            'simple',
                            coalesce(search_text, file_path || E'\n' || content)
                        )
                    WHERE search_text IS NULL
                       OR search_vector IS NULL;
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_code_chunks_project_name
                        ON code_chunks (project_name);
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_code_chunks_file_path
                        ON code_chunks (file_path);
                    """
                )
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_code_chunks_project_file_chunk
                        ON code_chunks (project_name, file_path, chunk_index);
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_code_chunks_symbol_name
                        ON code_chunks (symbol_name);
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_code_chunks_embedding
                        ON code_chunks
                        USING ivfflat (embedding vector_cosine_ops)
                        WITH (lists = 100);
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_code_chunks_search_vector
                        ON code_chunks
                        USING gin (search_vector);
                    """
                )
                conn.commit()

        _SCHEMA_READY = True


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


def _tsquery_text(query: str) -> str:
    terms = sorted(_tokenize_query(query))
    if not terms:
        return normalize_text(query)
    return " | ".join(terms)


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


def _merge_candidate_rows(*row_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, int], dict[str, Any]] = {}

    for rows in row_groups:
        for row in rows:
            key = (str(row.get("file_path", "")), int(row.get("chunk_index", 0)))
            current = merged.get(key)
            if current is None:
                merged[key] = dict(row)
                continue

            for field in ("score", "semantic_score", "lexical_db_score"):
                current[field] = max(
                    float(current.get(field, 0.0)),
                    float(row.get(field, 0.0)),
                )
            for field in (
                "symbol_name",
                "symbol_type",
                "path_tokens",
                "start_line",
                "end_line",
                "language",
                "content",
            ):
                if not current.get(field) and row.get(field):
                    current[field] = row.get(field)

    return list(merged.values())


def _rerank_results(query: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    settings = get_settings()
    reranked: list[dict[str, Any]] = []
    for row in rows:
        semantic_score = float(row.get("semantic_score", row.get("score", 0.0)))
        lexical_db_score = float(row.get("lexical_db_score", 0.0))
        lexical_score = _lexical_bonus(row, query)
        final_score = (
            semantic_score
            + lexical_score
            + (lexical_db_score * settings.lexical_db_score_weight)
        )
        updated = dict(row)
        updated["semantic_score"] = semantic_score
        updated["lexical_db_score"] = lexical_db_score
        updated["lexical_score"] = lexical_score
        updated["score"] = final_score
        reranked.append(updated)

    reranked.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    return reranked


def list_registered_projects() -> list[dict[str, Any]]:
    ensure_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    name,
                    project_path,
                    created_at,
                    updated_at,
                    last_indexed_at,
                    last_indexed_chunk_count
                FROM registered_projects
                ORDER BY name
                """
            )
            return list(cur.fetchall())


def get_registered_project(project_name: str) -> dict[str, Any] | None:
    ensure_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    name,
                    project_path,
                    created_at,
                    updated_at,
                    last_indexed_at,
                    last_indexed_chunk_count
                FROM registered_projects
                WHERE name = %s
                """,
                (project_name,),
            )
            return cur.fetchone()


def upsert_registered_project(project_name: str, project_path: str) -> dict[str, Any]:
    ensure_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO registered_projects (name, project_path)
                VALUES (%s, %s)
                ON CONFLICT (name)
                DO UPDATE SET
                    project_path = EXCLUDED.project_path,
                    updated_at = NOW()
                RETURNING
                    name,
                    project_path,
                    created_at,
                    updated_at,
                    last_indexed_at,
                    last_indexed_chunk_count
                """,
                (project_name, project_path),
            )
            row = cur.fetchone()
            conn.commit()
            return row


def delete_registered_project(project_name: str) -> bool:
    ensure_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM registered_projects WHERE name = %s",
                (project_name,),
            )
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted


def delete_project_chunks(project_name: str) -> int:
    ensure_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM code_chunks WHERE project_name = %s",
                (project_name,),
            )
            deleted = cur.rowcount
            conn.commit()
            return deleted


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

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM code_chunks WHERE project_name = %s",
                (project_name,),
            )
            cur.executemany(
                """
                INSERT INTO code_chunks (
                    project_name,
                    file_path,
                    chunk_index,
                    language,
                    symbol_name,
                    symbol_type,
                    path_tokens,
                    search_text,
                    search_vector,
                    start_line,
                    end_line,
                    content,
                    embedding
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    to_tsvector('simple', %s),
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                [
                    (
                        project_name,
                        file_path,
                        chunk_index,
                        language,
                        symbol_name,
                        symbol_type,
                        path_tokens,
                        search_text,
                        search_text,
                        start_line,
                        end_line,
                        content,
                        embedding,
                    )
                    for (
                        file_path,
                        chunk_index,
                        language,
                        symbol_name,
                        symbol_type,
                        path_tokens,
                        search_text,
                        start_line,
                        end_line,
                        content,
                        embedding,
                    ) in rows
                ],
            )
            cur.execute(
                """
                UPDATE registered_projects
                SET
                    updated_at = NOW(),
                    last_indexed_at = NOW(),
                    last_indexed_chunk_count = %s
                WHERE name = %s
                """,
                (len(rows), project_name),
            )
            conn.commit()

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
    from repo_code_indexer.index_flow import embed_texts

    settings = get_settings()
    query_vector = embed_texts(settings.embedding_model, [query])[0]
    tsquery_text = _tsquery_text(query)
    effective_min_score = settings.query_min_score if min_score is None else min_score
    candidate_limit = max(limit * settings.query_candidate_multiplier, limit)

    ensure_tables()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH filtered AS MATERIALIZED (
                    SELECT
                        project_name,
                        file_path,
                        chunk_index,
                        language,
                        symbol_name,
                        symbol_type,
                        path_tokens,
                        start_line,
                        end_line,
                        content,
                        embedding
                    FROM code_chunks
                    WHERE project_name = %s
                )
                SELECT
                    project_name,
                    file_path,
                    chunk_index,
                    language,
                    symbol_name,
                    symbol_type,
                    path_tokens,
                    start_line,
                    end_line,
                    content,
                    1 - (embedding <=> %s::vector) AS score,
                    1 - (embedding <=> %s::vector) AS semantic_score,
                    0.0 AS lexical_db_score
                FROM filtered
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    project_name,
                    query_vector,
                    query_vector,
                    query_vector,
                    candidate_limit,
                ),
            )
            semantic_rows = list(cur.fetchall())

            lexical_rows: list[dict[str, Any]] = []
            if tsquery_text.strip():
                cur.execute(
                    """
                    SELECT
                        project_name,
                        file_path,
                        chunk_index,
                        language,
                        symbol_name,
                        symbol_type,
                        path_tokens,
                        start_line,
                        end_line,
                        content,
                        0.0 AS score,
                        0.0 AS semantic_score,
                        ts_rank_cd(search_vector, to_tsquery('simple', %s)) AS lexical_db_score
                    FROM code_chunks
                    WHERE project_name = %s
                      AND search_vector @@ to_tsquery('simple', %s)
                    ORDER BY lexical_db_score DESC
                    LIMIT %s
                    """,
                    (tsquery_text, project_name, tsquery_text, candidate_limit),
                )
                lexical_rows = list(cur.fetchall())

    merged_rows = _merge_candidate_rows(semantic_rows, lexical_rows)
    reranked = _rerank_results(query, merged_rows)
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
            or float(row.get("lexical_db_score", 0.0)) > 0.0
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
