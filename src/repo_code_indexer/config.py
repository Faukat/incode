from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    state_dir: Path
    aws_region: str
    vector_bucket_name: str
    vector_index_prefix: str
    vector_distance_metric: str
    vector_put_batch_size: int
    embedding_model: str
    embedding_dimensions: int
    embedding_normalize: bool
    embedding_max_workers: int
    chunk_max_chars: int
    chunk_overlap: int
    default_query_limit: int
    query_min_score: float
    query_fallback_min_score: float
    query_candidate_multiplier: int
    query_embedding_cache_size: int
    lexical_db_score_weight: float
    result_preview_chars: int


def get_settings() -> Settings:
    repo_root = Path(os.getenv("REPO_INDEXER_ROOT", ".")).expanduser().resolve()
    state_dir = Path(
        os.getenv("REPO_INDEXER_STATE_DIR", Path.home() / ".incode")
    ).expanduser().resolve()

    return Settings(
        repo_root=repo_root,
        state_dir=state_dir,
        aws_region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        vector_bucket_name=os.getenv(
            "AWS_VECTOR_BUCKET_NAME", "incode-vectors"
        ),
        vector_index_prefix=os.getenv("AWS_VECTOR_INDEX_PREFIX", "incode"),
        vector_distance_metric=os.getenv("AWS_VECTOR_DISTANCE_METRIC", "cosine"),
        vector_put_batch_size=int(os.getenv("AWS_VECTOR_PUT_BATCH_SIZE", "25")),
        embedding_model=os.getenv(
            "EMBEDDING_MODEL",
            "amazon.titan-embed-text-v2:0",
        ),
        embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "512")),
        embedding_normalize=_env_bool("EMBEDDING_NORMALIZE", True),
        embedding_max_workers=int(os.getenv("EMBEDDING_MAX_WORKERS", "8")),
        chunk_max_chars=int(os.getenv("CHUNK_MAX_CHARS", "1600")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "200")),
        default_query_limit=int(os.getenv("QUERY_LIMIT", "5")),
        query_min_score=float(os.getenv("QUERY_MIN_SCORE", "0.10")),
        query_fallback_min_score=float(os.getenv("QUERY_FALLBACK_MIN_SCORE", "0.03")),
        query_candidate_multiplier=int(os.getenv("QUERY_CANDIDATE_MULTIPLIER", "2")),
        query_embedding_cache_size=int(os.getenv("QUERY_EMBED_CACHE_SIZE", "256")),
        lexical_db_score_weight=float(os.getenv("LEXICAL_DB_SCORE_WEIGHT", "0.25")),
        result_preview_chars=int(os.getenv("RESULT_PREVIEW_CHARS", "2000")),
    )


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(
        char for char in normalized if not unicodedata.combining(char)
    ).lower()
