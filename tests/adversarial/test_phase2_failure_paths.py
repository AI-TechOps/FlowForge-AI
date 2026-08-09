from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ValidationError


def test_audit_scrubber_redacts_database_url_and_connection_string_keys() -> None:
    from app.agents.audit import REDACTED, _scrub

    scrubbed = _scrub(
        {
            "database_url": "postgresql://operator:secret@db.internal/flowforge",
            "connection_string": "redis://:secret@redis.internal/0",
        }
    )
    assert scrubbed == {
        "database_url": REDACTED,
        "connection_string": REDACTED,
    }


def test_search_tool_clamps_oversized_k_to_the_server_limit() -> None:
    from app.agents.tools import SearchArgs
    from app.rag.retrieve import MAX_K

    args = SearchArgs.model_validate({"query": "vpn recovery", "k": MAX_K + 10_000})
    assert args.k == MAX_K


@pytest.mark.asyncio
async def test_invalid_tool_arguments_still_create_an_audit_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents import tools

    class StrictArgs(BaseModel):
        count: int

    async def handler(context: tools.ToolContext, args: StrictArgs) -> dict[str, int]:
        del context
        return {"count": args.count}

    audit_attempts: list[dict[str, Any]] = []

    @asynccontextmanager
    async def capture_audit(**kwargs: Any) -> Any:
        audit_attempts.append(kwargs)
        yield {}

    monkeypatch.setattr(tools.audit, "timed", capture_audit)
    tool = tools.Tool(
        name="strict_probe",
        description="adversarial typed-argument probe",
        args_model=StrictArgs,
        handler=handler,
    )
    context = tools.ToolContext(
        session=SimpleNamespace(),  # type: ignore[arg-type]
        org_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
    )

    with pytest.raises(ValidationError):
        await tool.invoke(context, {"count": "not-an-integer"})

    assert len(audit_attempts) == 1, (
        "a rejected typed tool invocation is still a tool call and must appear in audit_log"
    )


@pytest.mark.asyncio
async def test_cancelled_call_is_audited_before_cancellation_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents import audit

    records: list[dict[str, Any]] = []

    async def capture_record(**kwargs: Any) -> None:
        records.append(kwargs)

    monkeypatch.setattr(audit, "record", capture_record)
    with pytest.raises(asyncio.CancelledError):
        async with audit.timed(
            org_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            actor="agent",
            tool="llm.timeout_probe",
            payload={"attempt": 1},
        ):
            raise asyncio.CancelledError

    assert len(records) == 1, (
        "a timeout/cancellation must not erase the in-flight call from audit"
    )
    assert records[0]["result"]["error"] == "CancelledError"


@pytest.mark.asyncio
async def test_transient_llm_transport_failure_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("langgraph")
    from app.agents import graph
    from app.llm.provider import StructuredCompletion

    chunk_id = uuid.uuid4()
    valid_result = {
        "summary": "A grounded retry result",
        "category": "network_access",
        "urgency": "medium",
        "recommended_team": "IT Infrastructure",
        "suggested_priority": "P3",
        "recommended_resolution": "Follow the cited VPN recovery procedure.",
        "confidence": 0.8,
        "requires_approval": False,
        "citations": [
            {
                "chunk_id": str(chunk_id),
                "document_title": "VPN Access Policy",
                "page": 1,
                "section": "Recovery",
                "claim": "The documented recovery procedure applies.",
            }
        ],
    }

    class FlakyProvider:
        calls = 0

        async def complete_structured(
            self,
            prompt: str,
            schema: dict[str, Any],
            system: str | None = None,
        ) -> StructuredCompletion:
            del prompt, schema, system
            self.calls += 1
            if self.calls == 1:
                raise httpx.ConnectError("temporary provider disconnect")
            return StructuredCompletion(
                raw=json.dumps(valid_result),
                tokens_in=10,
                tokens_out=20,
                model="retry-probe",
            )

    provider = FlakyProvider()
    audited_calls: list[str] = []

    @asynccontextmanager
    async def capture_audit(**kwargs: Any) -> Any:
        audited_calls.append(str(kwargs["tool"]))
        yield {}

    monkeypatch.setattr(graph, "get_provider", lambda: provider)
    monkeypatch.setattr(graph.audit, "timed", capture_audit)
    context = SimpleNamespace(org_id=uuid.uuid4(), run_id=uuid.uuid4())
    state = {
        "ticket": {"title": "VPN retry probe", "description": "VPN disconnects"},
        "evidence": [
            {"chunk_id": str(chunk_id), "text": "Use the recovery procedure."}
        ],
    }

    result = await graph.classify(
        state,
        {"configurable": {"tool_context": context}},  # type: ignore[arg-type]
    )

    assert provider.calls == 2, "one transient transport failure should be retried"
    assert audited_calls == ["llm.classify", "llm.classify"]
    assert result.get("failure_reason") is None
    assert isinstance(result.get("result"), dict)


def test_openai_strict_schema_marks_every_object_property_required() -> None:
    """Finding 1, resolved at the transport layer.

    The probe originally asserted this of `TriageResult.model_json_schema()`.
    Making the domain model itself require every field would also force `page`
    and `section` to be present in model output, so a local model omitting a
    locator would fail schema validation outright — pushing runs to
    `schema_invalid` and working against G2.4. The strict rewrite therefore
    lives in the OpenAI adapter, and this asserts what is actually sent.
    """
    from app.agents.schema import TriageResult
    from app.llm.provider import _strict_schema

    schema = _strict_schema(TriageResult.model_json_schema())
    object_schemas = {"TriageResult": schema}
    object_schemas.update(
        {
            name: definition
            for name, definition in schema.get("$defs", {}).items()
            if definition.get("type") == "object"
        }
    )

    for name, object_schema in object_schemas.items():
        properties = set(object_schema.get("properties", {}))
        required = set(object_schema.get("required", []))
        assert required == properties, (
            f"OpenAI strict structured output requires every {name} property; "
            f"optional-in-schema={sorted(properties - required)}"
        )
