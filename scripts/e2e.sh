#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="${ROOT_DIR}/examples/sample-workspace"
PROJECT_NAME="${PROJECT_NAME:-projeto-a}"
MIN_SCORE="${MIN_SCORE:-0.10}"
export PROJECT_NAME
export MIN_SCORE

export REPO_INDEXER_ROOT="${REPO_INDEXER_ROOT:-$WORKSPACE_DIR}"
export REPO_INDEXER_STATE_DIR="${REPO_INDEXER_STATE_DIR:-$ROOT_DIR/.incode}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_VECTOR_BUCKET_NAME="${AWS_VECTOR_BUCKET_NAME:-incode-vectors}"
export AWS_VECTOR_INDEX_PREFIX="${AWS_VECTOR_INDEX_PREFIX:-incode}"
export EMBEDDING_MODEL="${EMBEDDING_MODEL:-amazon.titan-embed-text-v2:0}"
export EMBEDDING_DIMENSIONS="${EMBEDDING_DIMENSIONS:-512}"
export EMBEDDING_NORMALIZE="${EMBEDDING_NORMALIZE:-true}"

echo "[1/4] Preparando servico"
uv run incode setup

echo "[2/4] Registrando e indexando projeto ${PROJECT_NAME}"
uv run incode add-project "${PROJECT_NAME}" "${WORKSPACE_DIR}/${PROJECT_NAME}"
uv run incode index "${PROJECT_NAME}"

echo "[3/4] Consultando semanticamente"
uv run python - <<'PY'
import os
import sys

from repo_code_indexer.search import search_code

project_name = os.getenv("PROJECT_NAME", "projeto-a")
query = "onde fica a autenticacao?"
min_score = float(os.getenv("MIN_SCORE", "0.10"))

search_result = search_code(project_name, query, limit=3)
results = search_result["results"]

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

