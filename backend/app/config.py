from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Embedding dimension is a build-time constant, not an env var: the pgvector
# column type in the chunks migration is fixed at this width. Changing model
# families means a new migration + re-embed (see Phase 1 spec, Risks).
EMBEDDING_DIM = 768


class Settings(BaseSettings):
    """Application settings, read from environment variables (or a local .env).

    Every required variable is documented in .env.example at the repo root.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    # "fake" is a deterministic offline provider for CI/tests only (D15);
    # the provider factory refuses it when app_env == "prod".
    llm_provider: Literal["ollama", "openai", "fake"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str | None = None
    embedding_model: str = "nomic-embed-text"
    # Chat model for triage. Phase 5's eval judge must differ from this (D5).
    triage_model: str = "llama3.1:8b"
    # Failure injection for the fake provider (dev/CI only, D16):
    # valid | bad_enum | unparseable | no_citations.
    fake_llm_mode: str = "valid"
    app_env: Literal["dev", "prod"] = "dev"
    upload_dir: str = "/data/uploads"
    max_upload_mb: int = 20
    chunk_target_tokens: int = 500
    chunk_overlap_tokens: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()
