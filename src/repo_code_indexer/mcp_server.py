from __future__ import annotations

import os
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

mcp = FastMCP("repo-code-indexer")


def _resolve_root(root: str | None = None) -> Path:
    env_root = os.getenv("REPO_INDEXER_ROOT")
    if root:
        return Path(root).expanduser().resolve()
    if env_root:
        return Path(env_root).expanduser().resolve()
    return get_settings().repo_root


@mcp.tool
def list_projects_tool(root: str | None = None) -> dict[str, Any]:
    """
    Lista projetos registrados. Quando `root` for informado, lista os projetos descobertos nessa raiz.
    """
    if root:
        return discover_projects_service(str(_resolve_root(root)), register=False)
    return list_registered_projects_service()


@mcp.tool
def setup_service_tool() -> dict[str, Any]:
    """
    Prepara o banco e retorna a configuracao principal do servico.
    """
    return setup_service()


@mcp.tool
def register_project_tool(
    project_name: str,
    project_path: str | None = None,
) -> dict[str, Any]:
    """
    Registra ou atualiza um projeto para indexacao.
    """
    return register_project_service(project_name, project_path)


@mcp.tool
def discover_projects_tool(
    root: str | None = None,
    register: bool = False,
) -> dict[str, Any]:
    """
    Descobre projetos sob uma raiz e opcionalmente registra todos eles.
    """
    return discover_projects_service(
        str(_resolve_root(root)) if root else None, register=register
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
    return index_project_service(project_name)


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
    return search_project_service(
        project_name,
        query,
        limit=limit,
        min_score=min_score,
    )


def run() -> None:
    settings = get_settings()
    setup_service()
    warm_embedding_model(settings.embedding_model)
    mcp.run()


if __name__ == "__main__":
    run()
