from __future__ import annotations

from pathlib import Path


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".turbo",
    ".cache",
    "coverage",
    ".pytest_cache",
}


def list_projects(root: Path) -> list[Path]:
    if not root.exists():
        return []

    projects: list[Path] = []
    for item in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_dir():
            continue
        if item.name in IGNORED_DIRS:
            continue
        projects.append(item)
    return projects


def choose_project_interactive(projects: list[Path]) -> Path:
    if not projects:
        raise ValueError("Nenhum projeto encontrado.")

    print("\nProjetos encontrados:\n")
    for idx, project in enumerate(projects, start=1):
        print(f"{idx:>2}. {project.name}")

    while True:
        raw = input("\nEscolha o numero do projeto: ").strip()
        if not raw.isdigit():
            print("Digite um numero valido.")
            continue

        choice = int(raw)
        if 1 <= choice <= len(projects):
            return projects[choice - 1]

        print("Opcao fora da faixa.")
