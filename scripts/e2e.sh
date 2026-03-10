#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="${ROOT_DIR}/examples/sample-workspace"
PROJECT_NAME="${PROJECT_NAME:-projeto-a}"
MIN_SCORE="${MIN_SCORE:-0.10}"
export PROJECT_NAME
export MIN_SCORE

export REPO_INDEXER_ROOT="${REPO_INDEXER_ROOT:-$WORKSPACE_DIR}"
export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export POSTGRES_DB="${POSTGRES_DB:-code_indexer}"
export POSTGRES_USER="${POSTGRES_USER:-postgres}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
export EMBEDDING_MODEL="${EMBEDDING_MODEL:-sentence-transformers/all-MiniLM-L6-v2}"

echo "[1/4] Preparando servico"
uv run repo-indexer setup

echo "[2/4] Registrando e indexando projeto ${PROJECT_NAME}"
uv run repo-indexer add-project "${PROJECT_NAME}" "${WORKSPACE_DIR}/${PROJECT_NAME}"
uv run repo-indexer index "${PROJECT_NAME}"

echo "[3/4] Consultando semanticamente"
uv run python - <<'PY'
import os
import sys

from repo_code_indexer.search import search_code

project_name = os.getenv("PROJECT_NAME", "projeto-a")
query = "onde fica a autenticacao?"
min_score = float(os.getenv("MIN_SCORE", "0.10"))

results = search_code(project_name, query, limit=3)

if not results:
    print("[ERRO] Nenhum resultado encontrado para a consulta semantica.")
    sys.exit(1)

best = results[0]
score = float(best.get("score", 0.0))

print(f"Melhor resultado: {best.get('file_path')} | score={score:.4f}")

if score < min_score:
    print(
        f"[ERRO] Score abaixo do minimo esperado: {score:.4f} < {min_score:.4f}"
    )
    sys.exit(1)

print(f"Score minimo validado: {score:.4f} >= {min_score:.4f}")
PY

echo "[4/4] E2E finalizado com sucesso"
