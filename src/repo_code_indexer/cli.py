from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from repo_code_indexer.config import get_settings
from repo_code_indexer.service import (
    discover_projects_service,
    index_all_projects_service,
    index_project_service,
    list_registered_projects_service,
    register_project_service,
    remove_project_service,
    search_project_service,
    setup_service,
)

app = typer.Typer(help="Indexador semantico de repositorios")
console = Console()


def _safe_console_text(value: str) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    return value.encode(encoding, errors="replace").decode(encoding, errors="replace")


@app.command()
def setup() -> None:
    result = setup_service()
    console.print("[green]Servico pronto.[/green]")
    console.print(f"Raiz padrao: {result['repo_root']}")
    console.print(f"State dir: {result['state_dir']}")
    console.print(f"AWS region: {result['aws_region']}")
    console.print(f"Vector bucket: {result['vector_bucket_name']}")
    console.print(
        f"Embeddings: {result['embedding_model']} dims={result['embedding_dimensions']} normalize={result['embedding_normalize']}"
    )
    console.print(
        f"Chunking: max={result['chunk_max_chars']} overlap={result['chunk_overlap']}"
    )
    console.print(f"Limite padrao de busca: {result['default_query_limit']}")
    console.print(f"Score minimo de busca: {result['query_min_score']}")
    console.print(f"Score minimo de fallback: {result['query_fallback_min_score']}")
    console.print(f"Cache de embedding de query: {result['query_embedding_cache_size']}")
    console.print(f"Metric: {result['vector_distance_metric']}")
    console.print(f"Peso lexical local: {result['lexical_db_score_weight']}")


@app.command()
def config() -> None:
    settings = get_settings()
    table = Table(title="Configuracao atual")
    table.add_column("Chave")
    table.add_column("Valor")
    table.add_row("REPO_INDEXER_ROOT", str(settings.repo_root))
    table.add_row("REPO_INDEXER_STATE_DIR", str(settings.state_dir))
    table.add_row("AWS_REGION", settings.aws_region)
    table.add_row("AWS_VECTOR_BUCKET_NAME", settings.vector_bucket_name)
    table.add_row("AWS_VECTOR_INDEX_PREFIX", settings.vector_index_prefix)
    table.add_row("AWS_VECTOR_DISTANCE_METRIC", settings.vector_distance_metric)
    table.add_row("AWS_VECTOR_PUT_BATCH_SIZE", str(settings.vector_put_batch_size))
    table.add_row("EMBEDDING_MODEL", settings.embedding_model)
    table.add_row("EMBEDDING_DIMENSIONS", str(settings.embedding_dimensions))
    table.add_row("EMBEDDING_NORMALIZE", str(settings.embedding_normalize))
    table.add_row("EMBEDDING_MAX_WORKERS", str(settings.embedding_max_workers))
    table.add_row("CHUNK_MAX_CHARS", str(settings.chunk_max_chars))
    table.add_row("CHUNK_OVERLAP", str(settings.chunk_overlap))
    table.add_row("QUERY_LIMIT", str(settings.default_query_limit))
    table.add_row("QUERY_MIN_SCORE", str(settings.query_min_score))
    table.add_row("QUERY_FALLBACK_MIN_SCORE", str(settings.query_fallback_min_score))
    table.add_row(
        "QUERY_CANDIDATE_MULTIPLIER", str(settings.query_candidate_multiplier)
    )
    table.add_row("QUERY_EMBED_CACHE_SIZE", str(settings.query_embedding_cache_size))
    table.add_row("LEXICAL_DB_SCORE_WEIGHT", str(settings.lexical_db_score_weight))
    table.add_row("RESULT_PREVIEW_CHARS", str(settings.result_preview_chars))
    console.print(table)


@app.command()
def discover(
    root: Path | None = typer.Option(None, help="Raiz para descoberta de projetos"),
    register: bool = typer.Option(
        False, "--register", help="Registra os projetos encontrados"
    ),
) -> None:
    result = discover_projects_service(str(root) if root else None, register=register)
    projects = result["projects"]

    if not projects:
        console.print("[yellow]Nenhum projeto encontrado na raiz informada.[/yellow]")
        return

    title = "Projetos descobertos"
    if register:
        title = "Projetos descobertos e registrados"

    table = Table(title=f"{title} em {result['root']}")
    table.add_column("Projeto")
    table.add_column("Caminho")
    table.add_column("Registrado")

    for project in projects:
        table.add_row(
            project["name"], project["path"], "sim" if project["registered"] else "nao"
        )

    console.print(table)


@app.command()
def add_project(
    project_name: str,
    project_path: str | None = typer.Argument(None),
) -> None:
    result = register_project_service(project_name, project_path)
    if not result.get("ok"):
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]Projeto registrado.[/green]")
    console.print(f"Nome: {result['name']}")
    console.print(f"Caminho: {result['project_path']}")


@app.command()
def remove_project(
    project_name: str,
    delete_chunks: bool = typer.Option(
        False,
        "--delete-chunks",
        help="Tambem remove os chunks indexados desse projeto",
    ),
) -> None:
    result = remove_project_service(project_name, delete_chunks=delete_chunks)
    if not result.get("ok"):
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]Projeto removido:[/green] {project_name}")
    if delete_chunks:
        console.print(f"Chunks removidos: {result['chunks_deleted']}")


@app.command()
def projects() -> None:
    result = list_registered_projects_service()
    projects = result["projects"]

    if not projects:
        console.print("[yellow]Nenhum projeto registrado.[/yellow]")
        console.print(
            "Use `uv run incode add-project` ou `uv run incode discover --register`."
        )
        return

    table = Table(title="Projetos registrados")
    table.add_column("Projeto")
    table.add_column("Caminho")
    table.add_column("Ultima indexacao")
    table.add_column("Chunks", justify="right")

    for project in projects:
        table.add_row(
            project["name"],
            project["project_path"],
            str(project["last_indexed_at"] or "-"),
            str(project["last_indexed_chunk_count"] or 0),
        )

    console.print(table)


def _choose_registered_project_name() -> str:
    result = list_registered_projects_service()
    projects = result["projects"]
    if not projects:
        console.print("[red]Nenhum projeto registrado.[/red]")
        raise typer.Exit(code=1)

    console.print("\nProjetos registrados:\n")
    for idx, project in enumerate(projects, start=1):
        console.print(f"{idx:>2}. {project['name']} -> {project['project_path']}")

    while True:
        raw = typer.prompt("Escolha o numero do projeto")
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(projects):
                return str(projects[choice - 1]["name"])
        console.print("[yellow]Opcao invalida.[/yellow]")


@app.command()
def index(
    project_name: str | None = typer.Argument(None),
    all_projects: bool = typer.Option(
        False, "--all", help="Indexa todos os projetos registrados"
    ),
) -> None:
    if all_projects:
        results = index_all_projects_service()["results"]
        if not results:
            console.print("[yellow]Nenhum projeto registrado para indexar.[/yellow]")
            return

        for result in results:
            if result.get("ok"):
                console.print(
                    f"[green]OK[/green] {result['project_name']} files={result['files_indexed']} chunks={result['chunks_indexed']}"
                )
            else:
                console.print(
                    f"[red]ERRO[/red] {result['project_name']}: {result['error']}"
                )
        return

    selected_name = project_name or _choose_registered_project_name()
    console.print(f"[cyan]Indexando projeto:[/cyan] {selected_name}")
    result = index_project_service(selected_name)
    if not result.get("ok"):
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"[green]Indexacao concluida.[/green] Projeto={result['project_name']} files={result['files_indexed']} chunks={result['chunks_indexed']}"
    )


@app.command()
def query(
    project_name: str,
    text: str,
    limit: int | None = typer.Option(None),
    min_score: float | None = typer.Option(None),
) -> None:
    settings = get_settings()
    result = search_project_service(project_name, text, limit, min_score=min_score)
    if not result.get("ok"):
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    results = result["results"]

    if not results:
        console.print(
            f"[yellow]Nenhum resultado encontrado acima do score minimo {result['min_score']:.2f}.[/yellow]"
        )
        console.print(
            "Tente `--min-score 0.05`, use termos do repositorio como `auth`, `login`, `token` ou reindexe o projeto."
        )
        return

    if result.get("used_fallback"):
        console.print(
            f"[yellow]Mostrando resultados de fallback acima de {result['applied_min_score']:.2f} porque nenhum trecho passou no limiar principal.[/yellow]"
        )

    for idx, row in enumerate(results, start=1):
        console.rule(f"Resultado {idx} | score={row['score']:.4f}")
        console.print(f"[bold]Arquivo:[/bold] {row['file_path']}")
        console.print(f"[bold]Linguagem:[/bold] {row['language']}")
        if row.get("symbol_name"):
            console.print(
                f"[bold]Simbolo:[/bold] {row['symbol_name']} ({row.get('symbol_type') or 'chunk'})"
            )
        if row.get("start_line") and row.get("end_line"):
            console.print(
                f"[bold]Linhas:[/bold] {row['start_line']} - {row['end_line']}"
            )
        if "semantic_score" in row and "lexical_score" in row:
            console.print(
                f"[bold]Score semantico:[/bold] {row['semantic_score']:.4f} | [bold]Bonus lexical:[/bold] {row['lexical_score']:.4f}"
            )
        console.print(
            _safe_console_text(row["content"][: settings.result_preview_chars])
        )


if __name__ == "__main__":
    app()

