"""LLM provider abstraction (D11): the ONLY module that knows which provider is active.

Nothing else in app/ may import a provider SDK or reference a provider by name.
Providers talk HTTP via httpx directly — no vendor SDKs. Completion lands in
Phase 2 (triage agent); embeddings are implemented here since Phase 1.
"""

import hashlib
import json
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import EMBEDDING_DIM, Settings, get_settings

UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


@dataclass(frozen=True)
class StructuredCompletion:
    """Raw model output plus usage. Validation happens in the caller so the
    repair loop can see exactly what the model said (spec 03 §5)."""

    raw: str
    tokens_in: int
    tokens_out: int
    model: str


class LLMProvider(ABC):
    """Contract every provider implements. Kept minimal until Phase 2 needs more."""

    @abstractmethod
    async def complete(self, prompt: str) -> str:
        """Return a completion for the prompt."""

    @abstractmethod
    async def complete_structured(
        self, prompt: str, schema: dict[str, Any], system: str | None = None
    ) -> StructuredCompletion:
        """Return JSON text constrained to `schema` (provider-native mode, D16)."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector (EMBEDDING_DIM wide) per input text."""


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, embedding_model: str, chat_model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.embedding_model = embedding_model
        self.chat_model = chat_model

    async def complete(self, prompt: str) -> str:
        result = await self._chat(prompt, None, None)
        return result.raw

    async def complete_structured(
        self, prompt: str, schema: dict[str, Any], system: str | None = None
    ) -> StructuredCompletion:
        # Ollama constrains decoding to the JSON schema passed as `format`.
        return await self._chat(prompt, schema, system)

    async def _chat(
        self, prompt: str, schema: dict[str, Any] | None, system: str | None
    ) -> StructuredCompletion:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": self.chat_model,
            "messages": messages,
            "stream": False,
            # Deterministic decoding: triage is a classification task, and
            # reproducibility matters for eval comparability (Phase 5).
            "options": {"temperature": 0},
        }
        if schema is not None:
            body["format"] = schema

        async with httpx.AsyncClient(base_url=self.base_url, timeout=180.0) as client:
            response = await client.post("/api/chat", json=body)
            response.raise_for_status()
            payload = response.json()
        return StructuredCompletion(
            raw=payload["message"]["content"],
            tokens_in=int(payload.get("prompt_eval_count") or 0),
            tokens_out=int(payload.get("eval_count") or 0),
            model=self.chat_model,
        )

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
    def __init__(self, api_key: str, embedding_model: str, chat_model: str) -> None:
        self.api_key = api_key
        self.embedding_model = embedding_model
        self.chat_model = chat_model

    async def complete(self, prompt: str) -> str:
        result = await self._chat(prompt, None, None)
        return result.raw

    async def complete_structured(
        self, prompt: str, schema: dict[str, Any], system: str | None = None
    ) -> StructuredCompletion:
        return await self._chat(prompt, schema, system)

    async def _chat(
        self, prompt: str, schema: dict[str, Any] | None, system: str | None
    ) -> StructuredCompletion:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": self.chat_model,
            "messages": messages,
            "temperature": 0,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "triage_result",
                    "schema": schema,
                    "strict": True,
                },
            }

        async with httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=180.0,
        ) as client:
            response = await client.post("/chat/completions", json=body)
            response.raise_for_status()
            payload = response.json()
        usage = payload.get("usage") or {}
        return StructuredCompletion(
            raw=payload["choices"][0]["message"]["content"],
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            model=self.chat_model,
        )

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

    def __init__(self, embedding_model: str, mode: str = "valid") -> None:
        # Prefixed so chunks embedded by the fake provider can never be
        # mistaken for real model vectors (embedding_model is stored per chunk).
        self.embedding_model = f"fake:{embedding_model}"
        # Failure injection for the gates (D16): the schema/enum/grounding
        # gates must be shown to FAIL CLOSED, not merely to pass when happy.
        self.mode = mode

    async def complete(self, prompt: str) -> str:
        raise NotImplementedError("The fake provider does not complete prompts.")

    async def complete_structured(
        self, prompt: str, schema: dict[str, Any], system: str | None = None
    ) -> StructuredCompletion:
        """Deterministic, schema-shaped output. Not semantic.

        The fake proves plumbing — schema handling, grounding enforcement,
        audit completeness — never answer quality. Eval accuracy measured
        against fake output would be meaningless, which is why G2.4 is a
        real-model gate.

        Citations are built from chunk ids found in the prompt, so an empty
        knowledge base naturally yields zero citations and the grounding gate
        fires (G2.2) without any special-casing.
        """
        if self.mode == "unparseable":
            return self._result("not json at all {", prompt)
        resolved = _resolve_refs(schema, schema)
        value = _fake_value(resolved, prompt, seed=prompt, mode=self.mode)
        return self._result(json.dumps(value), prompt)

    def _result(self, raw: str, prompt: str) -> StructuredCompletion:
        return StructuredCompletion(
            raw=raw,
            tokens_in=len(prompt.split()),
            tokens_out=len(raw.split()),
            model=f"fake:{self.mode}",
        )

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


def _resolve_refs(node: Any, root: dict[str, Any]) -> Any:
    """Inline $ref/$defs so the generator can walk a single tree.

    Pydantic emits Citation as a $ref into $defs; the fake provider needs the
    expanded shape. Cycles are not expected in these schemas.
    """
    if isinstance(node, dict):
        if "$ref" in node:
            path = node["$ref"].removeprefix("#/").split("/")
            target: Any = root
            for part in path:
                target = target[part]
            return _resolve_refs(target, root)
        return {key: _resolve_refs(value, root) for key, value in node.items() if key != "$defs"}
    if isinstance(node, list):
        return [_resolve_refs(item, root) for item in node]
    return node


def _pick(options: list[Any], seed: str, salt: str) -> Any:
    digest = hashlib.sha256(f"{salt}:{seed}".encode()).digest()
    return options[int.from_bytes(digest[:4], "big") % len(options)]


def _fake_value(
    schema: dict[str, Any], prompt: str, seed: str, mode: str, field: str = ""
) -> Any:
    """Build a deterministic value satisfying `schema`.

    Handles the shapes the triage schema actually uses (enums, bounded strings
    and numbers, booleans, arrays of objects). It is not a general JSON Schema
    generator and does not pretend to be.
    """
    if "anyOf" in schema:
        # Optional fields (T | None): take the first non-null branch.
        branches = [b for b in schema["anyOf"] if b.get("type") != "null"]
        return _fake_value(branches[0], prompt, seed, mode, field) if branches else None

    if "enum" in schema:
        if mode == "bad_enum":
            return "definitely_not_a_valid_enum_member"
        return _pick(list(schema["enum"]), seed, field)

    node_type = schema.get("type")

    if node_type == "object":
        properties: dict[str, Any] = schema.get("properties", {})
        return {
            name: _fake_value(sub, prompt, seed, mode, field=name)
            for name, sub in properties.items()
        }

    if node_type == "array":
        if field == "citations":
            if mode == "no_citations":
                return []
            # Ground the answer in chunk ids actually present in the prompt.
            chunk_ids = list(dict.fromkeys(UUID_PATTERN.findall(prompt)))[:2]
            return [
                _citation(chunk_id, schema.get("items", {}), prompt, seed, mode)
                for chunk_id in chunk_ids
            ]
        return []

    if node_type == "boolean":
        return True

    if node_type in {"number", "integer"}:
        low = schema.get("minimum", 0)
        high = schema.get("maximum", 1 if node_type == "number" else 100)
        digest = hashlib.sha256(f"{field}:{seed}".encode()).digest()
        fraction = int.from_bytes(digest[:2], "big") / 65535
        value = low + (high - low) * fraction
        return round(value, 2) if node_type == "number" else int(value)

    if node_type == "string":
        text = f"fake {field or 'value'}: deterministic stand-in for offline gates"
        maximum = schema.get("maxLength")
        return text[:maximum] if maximum else text

    return None


def _citation(
    chunk_id: str, item_schema: dict[str, Any], prompt: str, seed: str, mode: str
) -> dict[str, Any]:
    citation = _fake_value(item_schema, prompt, seed=chunk_id, mode=mode, field="citation")
    if isinstance(citation, dict):
        citation["chunk_id"] = chunk_id
    return citation


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
        return OpenAIProvider(api_key, settings.embedding_model, settings.triage_model)
    if settings.llm_provider == "fake":
        if settings.app_env == "prod":
            raise ValueError("LLM_PROVIDER=fake is for dev/CI only, never prod.")
        return FakeProvider(settings.embedding_model, settings.fake_llm_mode)
    return OllamaProvider(
        settings.ollama_base_url, settings.embedding_model, settings.triage_model
    )
