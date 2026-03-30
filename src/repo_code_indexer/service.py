from __future__ import annotations

from pathlib import Path
from typing import Any

from repo_code_indexer.config import get_settings
from repo_code_indexer.projects import list_projects


def _search_api():
    from repo_code_indexer import search

    return search


def _resolve_path(project_name: str, project_path: str | None = None) -> Path:
    settings = get_settings()

    if project_path:
        candidate = Path(project_path).expanduser()
        if not candidate.is_absolute():
            candidate = settings.repo_root / candidate
    else:
        candidate = settings.repo_root / project_name

    return candidate.resolve()


def setup_service() -> dict[str, Any]:
    from repo_code_indexer.index_flow import warm_embedding_model

    settings = get_settings()
    _search_api().ensure_tables()
    warm_embedding_model(settings.embedding_model)
    return {
        "ok": True,
        "repo_root": str(settings.repo_root),
        "state_dir": str(settings.state_dir),
        "aws_region": settings.aws_region,
        "vector_bucket_name": settings.vector_bucket_name,
        "vector_distance_metric": settings.vector_distance_metric,
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "embedding_normalize": settings.embedding_normalize,
        "chunk_max_chars": settings.chunk_max_chars,
        "chunk_overlap": settings.chunk_overlap,
        "default_query_limit": settings.default_query_limit,
        "query_min_score": settings.query_min_score,
        "query_fallback_min_score": settings.query_fallback_min_score,
        "query_candidate_multiplier": settings.query_candidate_multiplier,
        "query_embedding_cache_size": settings.query_embedding_cache_size,
        "lexical_db_score_weight": settings.lexical_db_score_weight,
    }


def list_registered_projects_service() -> dict[str, Any]:
    search = _search_api()
    search.ensure_tables()
    projects = search.list_registered_projects()
    return {
        "count": len(projects),
        "projects": projects,
    }


def discover_projects_service(
    root: str | None = None,
    register: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    base = Path(root).expanduser().resolve() if root else settings.repo_root
    discovered = list_projects(base)

    items: list[dict[str, Any]] = []
    for project in discovered:
        entry = {
            "name": project.name,
            "path": str(project.resolve()),
            "registered": False,
        }
        if register:
            stored = _search_api().upsert_registered_project(
                project.name, str(project.resolve())
            )
            entry.update(
                {
                    "registered": True,
                    "last_indexed_at": stored.get("last_indexed_at"),
                    "last_indexed_chunk_count": stored.get("last_indexed_chunk_count"),
                }
            )
        items.append(entry)

    return {
        "root": str(base),
        "count": len(items),
        "projects": items,
        "registered": register,
    }


def register_project_service(
    project_name: str,
    project_path: str | None = None,
) -> dict[str, Any]:
    if not project_name.strip():
        return {
            "ok": False,
            "error": "Nome do projeto nao pode ser vazio.",
        }

    resolved_path = _resolve_path(project_name, project_path)
    if not resolved_path.exists():
        return {
            "ok": False,
            "error": f"Caminho nao encontrado: {resolved_path}",
        }
    if not resolved_path.is_dir():
        return {
            "ok": False,
            "error": f"Caminho nao e um diretorio: {resolved_path}",
        }

    project = _search_api().upsert_registered_project(project_name, str(resolved_path))
    project["ok"] = True
    return project


def remove_project_service(
    project_name: str,
    delete_chunks: bool = False,
) -> dict[str, Any]:
    search = _search_api()
    existing = search.get_registered_project(project_name)
    if existing is None:
        return {
            "ok": False,
            "error": f"Projeto nao registrado: {project_name}",
        }

    deleted = search.delete_registered_project(project_name)
    chunks_deleted = 0
    if delete_chunks:
        search.delete_project_chunks(project_name)
        chunks_deleted = int(existing.get("last_indexed_chunk_count") or 0)

    return {
        "ok": deleted,
        "project_name": project_name,
        "chunks_deleted": chunks_deleted,
    }


def index_project_service(project_name: str) -> dict[str, Any]:
    from repo_code_indexer.index_flow import build_chunks, embed_texts

    settings = get_settings()
    search = _search_api()
    project = search.get_registered_project(project_name)
    if project is None:
        return {
            "ok": False,
            "error": f"Projeto nao registrado: {project_name}",
        }

    project_dir = Path(project["project_path"]).expanduser().resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        return {
            "ok": False,
            "error": f"Diretorio do projeto nao encontrado: {project_dir}",
            "project_name": project_name,
        }

    chunks = build_chunks(
        project_dir,
        max_chars=settings.chunk_max_chars,
        overlap=settings.chunk_overlap,
    )
    if not chunks:
        return {
            "ok": False,
            "error": "Nenhum chunk gerado para indexacao.",
            "project_name": project_name,
            "project_path": str(project_dir),
        }

    texts = [chunk.search_text for chunk in chunks]
    vectors = embed_texts(settings.embedding_model, texts)

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
    ] = [
        (
            chunk.file_path,
            chunk.chunk_index,
            chunk.language,
            chunk.symbol_name,
            chunk.symbol_type,
            chunk.path_tokens,
            chunk.search_text,
            chunk.start_line,
            chunk.end_line,
            chunk.content,
            vector,
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]

    inserted = search.replace_project_chunks(project_name, rows)
    return {
        "ok": True,
        "project_name": project_name,
        "project_path": str(project_dir),
        "files_indexed": len({chunk.file_path for chunk in chunks}),
        "chunks_indexed": inserted,
    }


def index_all_projects_service() -> dict[str, Any]:
    search = _search_api()
    search.ensure_tables()
    projects = search.list_registered_projects()
    results = [index_project_service(project["name"]) for project in projects]
    return {
        "count": len(results),
        "results": results,
    }


def search_project_service(
    project_name: str,
    query: str,
    limit: int | None = None,
    min_score: float | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    search = _search_api()
    project = search.get_registered_project(project_name)
    if project is None:
        return {
            "ok": False,
            "error": f"Projeto nao registrado: {project_name}",
            "project_name": project_name,
        }

    effective_limit = limit if limit is not None else settings.default_query_limit
    search_result = search.search_code(
        project_name,
        query,
        effective_limit,
        min_score=min_score,
    )
    return {
        "ok": True,
        "project_name": project_name,
        "query": query,
        "min_score": settings.query_min_score if min_score is None else min_score,
        "applied_min_score": search_result["applied_min_score"],
        "used_fallback": search_result["used_fallback"],
        "count": len(search_result["results"]),
        "results": search_result["results"],
    }
