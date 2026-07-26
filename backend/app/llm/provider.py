"""LLM provider abstraction (D11): the ONLY module that knows which provider is active.

Nothing else in app/ may import a provider SDK or reference a provider by name.
Providers talk HTTP via httpx directly — no vendor SDKs. Completion lands in
Phase 2 (triage agent); embeddings are implemented here since Phase 1.
"""

import hashlib
import math
import re
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

    Embeddings are a deterministic *feature hashing* of the text's tokens (the
    hashing-vectorizer trick): each token is hashed to a signed bucket in an
    EMBEDDING_DIM vector, which is then L2-normalized. Texts that share
    vocabulary land near each other under cosine similarity, so the retrieval
    sanity gates (G1.1/G1.2) exercise real ranking behaviour offline — a plain
    whole-text hash would be deterministic but semantically blind. Identical
    text always embeds identically. Refused in prod by the factory.
    """

    _TOKEN = re.compile(r"[a-z0-9]+")
    _MIN_TOKEN_LEN = 3

    def __init__(self, embedding_model: str) -> None:
        # Prefixed so chunks embedded by the fake provider can never be
        # mistaken for real model vectors (embedding_model is stored per chunk).
        self.embedding_model = f"fake:{embedding_model}"

    async def complete(self, prompt: str) -> str:
        raise NotImplementedError("The fake provider does not complete prompts.")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    @classmethod
    def _embed_one(cls, text: str) -> list[float]:
        values = [0.0] * EMBEDDING_DIM
        tokens = [t for t in cls._TOKEN.findall(text.lower()) if len(t) >= cls._MIN_TOKEN_LEN]
        # No usable tokens (punctuation/whitespace only): fall back to the whole
        # string so the vector is still deterministic and non-zero.
        for token in tokens or [text.strip() or " "]:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIM
            sign = 1.0 if digest[4] & 1 else -1.0
            values[index] += sign
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
