"""LLM provider abstraction (D11): the ONLY module that knows which provider is active.

Nothing else in app/ may import a provider SDK or reference a provider by name.
Providers talk HTTP via httpx directly — no vendor SDKs. Completion lands in
Phase 2 (triage agent); embeddings are implemented here since Phase 1.
"""

import hashlib
import math
import struct
from abc import ABC, abstractmethod

import httpx

from app.config import EMBEDDING_DIM, Settings, get_settings


class LLMProvider(ABC):
    """Contract every provider implements. Kept minimal until Phase 2 needs more."""

    @abstractmethod
    async def complete(self, prompt: str) -> str:
        """Return a completion for the prompt."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector (EMBEDDING_DIM wide) per input text."""


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, embedding_model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.embedding_model = embedding_model

    async def complete(self, prompt: str) -> str:
        raise NotImplementedError("Implemented in Phase 2 (triage agent).")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=60.0) as client:
            response = await client.post(
                "/api/embed",
                json={"model": self.embedding_model, "input": texts},
            )
            response.raise_for_status()
            embeddings: list[list[float]] = response.json()["embeddings"]
        _check_dimensions(embeddings)
        return embeddings


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, embedding_model: str) -> None:
        self.api_key = api_key
        self.embedding_model = embedding_model

    async def complete(self, prompt: str) -> str:
        raise NotImplementedError("Implemented in Phase 2 (triage agent).")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60.0,
        ) as client:
            response = await client.post(
                "/embeddings",
                json={
                    "model": self.embedding_model,
                    "input": texts,
                    "dimensions": EMBEDDING_DIM,
                },
            )
            response.raise_for_status()
            payload = response.json()
        embeddings = [item["embedding"] for item in payload["data"]]
        _check_dimensions(embeddings)
        return embeddings


class FakeProvider(LLMProvider):
    """Deterministic offline provider for CI and tests (Phase 1 decision, D15).

    Vectors are derived from a SHA-256 stream over the text, L2-normalized so
    cosine similarity behaves sensibly. Identical text always embeds
    identically. Refused in prod by the factory.
    """

    def __init__(self, embedding_model: str) -> None:
        self.embedding_model = embedding_model

    async def complete(self, prompt: str) -> str:
        raise NotImplementedError("The fake provider does not complete prompts.")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    @staticmethod
    def _embed_one(text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        seed = text.encode("utf-8")
        while len(values) < EMBEDDING_DIM:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            for offset in range(0, len(digest) - 3, 4):
                (raw,) = struct.unpack_from(">i", digest, offset)
                values.append(raw / 2**31)
                if len(values) == EMBEDDING_DIM:
                    break
            counter += 1
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]


def _check_dimensions(embeddings: list[list[float]]) -> None:
    for vector in embeddings:
        if len(vector) != EMBEDDING_DIM:
            raise ValueError(
                f"provider returned a {len(vector)}-dim embedding; "
                f"expected {EMBEDDING_DIM} (EMBEDDING_DIM)"
            )


def get_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    if settings.llm_provider == "openai":
        api_key = (settings.openai_api_key or "").strip()
        if not api_key:
            raise ValueError(
                "LLM_PROVIDER=openai requires OPENAI_API_KEY to be set to a non-blank value."
            )
        return OpenAIProvider(api_key, settings.embedding_model)
    if settings.llm_provider == "fake":
        if settings.app_env == "prod":
            raise ValueError("LLM_PROVIDER=fake is for dev/CI only, never prod.")
        return FakeProvider(settings.embedding_model)
    return OllamaProvider(settings.ollama_base_url, settings.embedding_model)
