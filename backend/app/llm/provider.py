"""LLM provider abstraction (D11): the ONLY module that knows which provider is active.

Nothing else in app/ may import a provider SDK or reference a provider by name.
Phase 0 ships the interface and factory only; real implementations land in
Phase 1 (embeddings) and Phase 2 (completion).
"""

from abc import ABC, abstractmethod

from app.config import Settings, get_settings


class LLMProvider(ABC):
    """Contract every provider implements. Kept minimal until Phases 1-2 need more."""

    @abstractmethod
    async def complete(self, prompt: str) -> str:
        """Return a completion for the prompt."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, embedding_model: str) -> None:
        self.base_url = base_url
        self.embedding_model = embedding_model

    async def complete(self, prompt: str) -> str:
        raise NotImplementedError("Implemented in Phase 2 (triage agent).")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Implemented in Phase 1 (RAG ingestion).")


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, embedding_model: str) -> None:
        self.api_key = api_key
        self.embedding_model = embedding_model

    async def complete(self, prompt: str) -> str:
        raise NotImplementedError("Implemented in Phase 2 (triage agent).")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Implemented in Phase 1 (RAG ingestion).")


def get_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    if settings.llm_provider == "openai":
        api_key = (settings.openai_api_key or "").strip()
        if not api_key:
            raise ValueError(
                "LLM_PROVIDER=openai requires OPENAI_API_KEY to be set to a non-blank value."
            )
        return OpenAIProvider(api_key, settings.embedding_model)
    return OllamaProvider(settings.ollama_base_url, settings.embedding_model)
