from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables (or a local .env).

    Every required variable is documented in .env.example at the repo root.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    llm_provider: Literal["ollama", "openai"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str | None = None
    embedding_model: str = "nomic-embed-text"
    app_env: Literal["dev", "prod"] = "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
