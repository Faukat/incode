from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from repo_code_indexer.config import get_settings
from repo_code_indexer.index_flow import warm_embedding_model
from repo_code_indexer.service import (
    discover_projects_service,
    index_project_service,
    list_registered_projects_service,
    register_project_service,
    remove_project_service,
    search_project_service,
    setup_service,
)

mcp = FastMCP("incode")
MCP_SNIPPET_CHARS = 400


def _resolve_root(root: str | None = None) -> Path:
    env_root = os.getenv("REPO_INDEXER_ROOT")
    if root:
        return Path(root).expanduser().resolve()
    if env_root:
        return Path(env_root).expanduser().resolve()
    return get_settings().repo_root


def _compact_project_item(project: dict[str, Any]) -> dict[str, Any]:
    item = {
        "name": project.get("name"),
        "project_path": project.get("project_path") or project.get("path"),
    }
    if "registered" in project:
        item["registered"] = bool(project.get("registered"))
    if project.get("last_indexed_at"):
        item["last_indexed_at"] = project.get("last_indexed_at")
    if project.get("last_indexed_chunk_count") is not None:
        item["last_indexed_chunk_count"] = int(project.get("last_indexed_chunk_count") or 0)
    return item


def _compact_setup_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(payload.get("ok")),
        "repo_root": payload.get("repo_root"),
        "state_dir": payload.get("state_dir"),
        "aws_region": payload.get("aws_region"),
        "vector_bucket_name": payload.get("vector_bucket_name"),
        "embedding_model": payload.get("embedding_model"),
        "embedding_dimensions": payload.get("embedding_dimensions"),
        "query_candidate_multiplier": payload.get("query_candidate_multiplier"),
        "query_embedding_cache_size": payload.get("query_embedding_cache_size"),
    }


def _compact_projects_payload(payload: dict[str, Any]) -> dict[str, Any]:
    response = {
        "count": int(payload.get("count") or 0),
        "projects": [_compact_project_item(project) for project in payload.get("projects", [])],
    }
    if payload.get("root"):
        response["root"] = payload.get("root")
    if "registered" in payload:
        response["registered"] = bool(payload.get("registered"))
    return response


def _compact_register_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("ok"):
        return payload
    return {
        "ok": True,
        "name": payload.get("name"),
        "project_path": payload.get("project_path"),
        "last_indexed_at": payload.get("last_indexed_at"),
        "last_indexed_chunk_count": int(payload.get("last_indexed_chunk_count") or 0),
    }


def _compact_index_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("ok"):
        return payload
    return {
        "ok": True,
        "project_name": payload.get("project_name"),
        "files_indexed": int(payload.get("files_indexed") or 0),
        "chunks_indexed": int(payload.get("chunks_indexed") or 0),
    }


def _snippet(value: str, limit: int = MCP_SNIPPET_CHARS) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def _compact_search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("ok"):
        return payload

    results: list[dict[str, Any]] = []
    for row in payload.get("results", []):
        item: dict[str, Any] = {
            "file_path": row.get("file_path"),
            "score": round(float(row.get("score", 0.0)), 4),
            "snippet": _snippet(str(row.get("content", ""))),
        }
        if row.get("symbol_name"):
            item["symbol_name"] = row.get("symbol_name")
        if row.get("symbol_type"):
            item["symbol_type"] = row.get("symbol_type")
        if row.get("language"):
            item["language"] = row.get("language")
        if row.get("start_line"):
            item["start_line"] = int(row.get("start_line") or 0)
        if row.get("end_line"):
            item["end_line"] = int(row.get("end_line") or 0)
        if row.get("semantic_score") is not None:
            item["semantic_score"] = round(float(row.get("semantic_score", 0.0)), 4)
        if row.get("lexical_score") is not None:
            item["lexical_score"] = round(float(row.get("lexical_score", 0.0)), 4)
        results.append(item)

    return {
        "ok": True,
        "project_name": payload.get("project_name"),
        "query": payload.get("query"),
        "count": int(payload.get("count") or 0),
        "used_fallback": bool(payload.get("used_fallback")),
        "applied_min_score": payload.get("applied_min_score"),
        "snippet_chars": MCP_SNIPPET_CHARS,
        "results": results,
    }


@mcp.tool
def list_projects_tool(root: str | None = None) -> dict[str, Any]:
    """
    Lista projetos registrados. Quando `root` for informado, lista os projetos descobertos nessa raiz.
    """
    if root:
        return _compact_projects_payload(
            discover_projects_service(str(_resolve_root(root)), register=False)
        )
    return _compact_projects_payload(list_registered_projects_service())


@mcp.tool
def setup_service_tool() -> dict[str, Any]:
    """
    Prepara o servico e retorna a configuracao principal.
    """
    return _compact_setup_payload(setup_service())


@mcp.tool
def register_project_tool(
    project_name: str,
    project_path: str | None = None,
) -> dict[str, Any]:
    """
    Registra ou atualiza um projeto para indexacao.
    """
    return _compact_register_payload(
        register_project_service(project_name, project_path)
    )


@mcp.tool
def discover_projects_tool(
    root: str | None = None,
    register: bool = False,
) -> dict[str, Any]:
    """
    Descobre projetos sob uma raiz e opcionalmente registra todos eles.
    """
    return _compact_projects_payload(
        discover_projects_service(
            str(_resolve_root(root)) if root else None, register=register
        )
    )


@mcp.tool
def remove_project_tool(
    project_name: str,
    delete_chunks: bool = False,
) -> dict[str, Any]:
    """
    Remove um projeto registrado e opcionalmente apaga seus chunks indexados.
    """
    return remove_project_service(project_name, delete_chunks=delete_chunks)


@mcp.tool
def index_project(project_name: str) -> dict[str, Any]:
    """
    Indexa um projeto previamente registrado.
    """
    return _compact_index_payload(index_project_service(project_name))


@mcp.tool
def search_code_tool(
    project_name: str,
    query: str,
    limit: int | None = None,
    min_score: float | None = None,
) -> dict[str, Any]:
    """
    Faz busca semantica dentro do projeto indexado.
    """
    return _compact_search_payload(
        search_project_service(
            project_name,
            query,
            limit=limit,
            min_score=min_score,
        )
    )


def run() -> None:
    settings = get_settings()
    setup_service()
    warm_embedding_model(settings.embedding_model)
    mcp.run()


if __name__ == "__main__":
    run()
