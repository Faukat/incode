from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    embedding_model: str
    chunk_max_chars: int
    chunk_overlap: int
    default_query_limit: int
    query_min_score: float
    query_fallback_min_score: float
    query_candidate_multiplier: int
    lexical_db_score_weight: float
    result_preview_chars: int

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def get_settings() -> Settings:
    repo_root = Path(os.getenv("REPO_INDEXER_ROOT", ".")).expanduser().resolve()

    return Settings(
        repo_root=repo_root,
        postgres_host=os.getenv("POSTGRES_HOST", "localhost"),
        postgres_port=int(os.getenv("POSTGRES_PORT", "5432")),
        postgres_db=os.getenv("POSTGRES_DB", "code_indexer"),
        postgres_user=os.getenv("POSTGRES_USER", "postgres"),
        postgres_password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        embedding_model=os.getenv(
            "EMBEDDING_MODEL",
            "sentence-transformers/all-MiniLM-L6-v2",
        ),
        chunk_max_chars=int(os.getenv("CHUNK_MAX_CHARS", "1600")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "200")),
        default_query_limit=int(os.getenv("QUERY_LIMIT", "5")),
        query_min_score=float(os.getenv("QUERY_MIN_SCORE", "0.10")),
        query_fallback_min_score=float(os.getenv("QUERY_FALLBACK_MIN_SCORE", "0.03")),
        query_candidate_multiplier=int(os.getenv("QUERY_CANDIDATE_MULTIPLIER", "5")),
        lexical_db_score_weight=float(os.getenv("LEXICAL_DB_SCORE_WEIGHT", "0.25")),
        result_preview_chars=int(os.getenv("RESULT_PREVIEW_CHARS", "2000")),
    )


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(
        char for char in normalized if not unicodedata.combining(char)
    ).lower()
