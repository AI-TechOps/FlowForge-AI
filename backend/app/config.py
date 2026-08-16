from functools import lru_cache
from typing import Literal

from pydantic import model_validator
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
    # The eval judge (D19 decision 1). A different family, not just a different
    # tag: two prompts on one model share its blind spots, which is precisely
    # what an independent score exists to catch. Validated below.
    judge_model: str = "qwen2.5:7b"
    # Failure injection for the fake provider (dev/CI only, D16):
    # valid | bad_enum | unparseable | no_citations.
    fake_llm_mode: str = "valid"
    app_env: Literal["dev", "prod"] = "dev"
    # Identity provider (D18 decision 1). "local" is an offline issuer for
    # dev/CI, refused by the auth factory when app_env == "prod" — the same
    # rule the fake LLM provider follows.
    auth_provider: Literal["auth0", "local"] = "local"
    auth0_domain: str | None = None
    # The API identifier configured in Auth0; becomes the token `aud` claim.
    auth0_audience: str | None = None
    # Public SPA client id. Not a secret — the frontend needs it to start PKCE.
    auth0_client_id: str | None = None
    # Lifetime of a locally issued dev token. Short: it exists to run a gate,
    # not to keep a session alive.
    dev_token_ttl_seconds: int = 3600
    upload_dir: str = "/data/uploads"
    max_upload_mb: int = 20
    chunk_target_tokens: int = 500
    chunk_overlap_tokens: int = 50
    run_timeout_seconds: int = 300
    worker_concurrency: int = 4
    # How many times a run may be picked up before it is dead-lettered
    # (spec 05 §4). Low on purpose: a job that has already killed its worker
    # twice is not going to succeed on the fifth try, it is going to occupy a
    # worker slot five times.
    max_run_attempts: int = 3
    # Per-write-tool timeout; well under run_timeout so a hung adapter surfaces
    # as a tool failure with its own retry, not as a whole-run timeout.
    tool_timeout_seconds: int = 30
    # Fault injection for the mock ticket system (dev/CI only):
    # none | timeout | error. A per-ticket [[FLOWFORGE_TICKET_FAULT:mode]]
    # directive overrides it for a single run.
    mock_ticket_fault: str = "none"

    @model_validator(mode="after")
    def _judge_differs_from_triage(self) -> "Settings":
        """D5, asserted at config load rather than at eval time (G5.2).

        Failing here means a misconfigured stack refuses to start. Failing at
        eval time would mean discovering it after a batch had been recorded
        against a judge that was grading its own output — and that batch would
        already be in the regression table.
        """
        if self.judge_model.strip() == self.triage_model.strip():
            raise ValueError(
                f"JUDGE_MODEL must differ from TRIAGE_MODEL (both are "
                f"{self.triage_model!r}). A model grading its own output shares "
                "its own blind spots — see D5."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
