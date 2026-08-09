"""The LangGraph triage graph.

    load_ticket → retrieve_evidence → classify → ground_check → propose

Control flow is deterministic (D16 decision 2): nodes invoke tools directly
rather than letting the model choose. That keeps step counts predictable, which
is what makes audit completeness (G2.5) checkable and the Phase 3 durable pause
tractable.

Non-serializable dependencies (DB session, org context) travel through
`config["configurable"]`, never through graph state — state must stay
JSON-serializable for the Postgres checkpointer.
"""

import asyncio
import logging
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from app.agents import audit
from app.agents.prompts import (
    AGENT_VERSION,
    REPAIR_PROMPT,
    TRIAGE_SYSTEM,
    build_triage_prompt,
)
from app.agents.schema import TriageResult
from app.agents.tools import ToolContext, get_tool
from app.agents.validate import is_grounded, parse_triage_result, valid_citations
from app.llm.cost import estimate_cost
from app.llm.provider import get_provider

logger = logging.getLogger(__name__)

MAX_CLASSIFY_ATTEMPTS = 2  # initial attempt + one repair retry (spec 03 §5)
MAX_TRANSPORT_ATTEMPTS = 2  # initial call + one retry on transport failure (spec 03 §6)
TRANSPORT_BACKOFF_SECONDS = 1.0


class TriageState(TypedDict, total=False):
    ticket_id: str
    ticket: dict[str, Any]
    evidence: list[dict[str, Any]]
    result: dict[str, Any] | None
    citations: list[dict[str, Any]]
    confidence: float | None
    failure_reason: str | None
    error: str | None
    agent_version: str


def _context(config: RunnableConfig) -> ToolContext:
    return config["configurable"]["tool_context"]


async def load_ticket(state: TriageState, config: RunnableConfig) -> TriageState:
    context = _context(config)
    ticket = await get_tool("get_ticket").invoke(context, {"ticket_id": state["ticket_id"]})
    return {"ticket": ticket, "agent_version": AGENT_VERSION}


async def retrieve_evidence(state: TriageState, config: RunnableConfig) -> TriageState:
    context = _context(config)
    ticket = state["ticket"]
    # The ticket itself is the query; the retriever handles the semantics.
    query = f"{ticket.get('title', '')}\n{ticket.get('description', '')}".strip()
    evidence = await get_tool("search_company_knowledge").invoke(context, {"query": query, "k": 5})
    return {"evidence": evidence}


async def _complete_with_retry(
    provider: Any,
    context: ToolContext,
    prompt: str,
    schema: dict[str, Any],
    attempt: int,
) -> Any:
    """One structured completion, retried on transport failure (spec 03 §6).

    Distinct from the repair retry in `classify`: that one answers "the model
    replied with something invalid", this one answers "the call never landed".
    A provider that drops one connection used to fail the entire run as
    internal_error (Codex Phase 2 finding 3).

    Every attempt is audited, including the ones that raise, so the trail still
    accounts for every LLM call (G2.5).
    """
    last_exc: Exception | None = None
    for transport_attempt in range(1, MAX_TRANSPORT_ATTEMPTS + 1):
        try:
            async with audit.timed(
                org_id=context.org_id,
                run_id=context.run_id,
                actor="agent",
                tool="llm.classify",
                payload={
                    "attempt": attempt,
                    "transport_attempt": transport_attempt,
                    "model_schema": "TriageResult",
                },
            ) as box:
                completion = await provider.complete_structured(
                    prompt, schema, system=TRIAGE_SYSTEM
                )
                box["tokens_in"] = completion.tokens_in
                box["tokens_out"] = completion.tokens_out
                box["cost_estimate"] = estimate_cost(
                    completion.model, completion.tokens_in, completion.tokens_out
                )
                box["result"] = {"raw_length": len(completion.raw), "model": completion.model}
            return completion
        except Exception as exc:  # noqa: BLE001 - any transport error is retryable once
            last_exc = exc
            if transport_attempt == MAX_TRANSPORT_ATTEMPTS:
                break
            backoff = TRANSPORT_BACKOFF_SECONDS * transport_attempt
            logger.warning(
                "llm transport attempt %d failed (%s); retrying in %.1fs",
                transport_attempt,
                exc,
                backoff,
            )
            await asyncio.sleep(backoff)

    assert last_exc is not None
    raise last_exc


async def classify(state: TriageState, config: RunnableConfig) -> TriageState:
    context = _context(config)
    provider = get_provider()
    schema = TriageResult.model_json_schema()
    prompt = build_triage_prompt(state["ticket"], state.get("evidence", []))

    last_error: str | None = None
    for attempt in range(1, MAX_CLASSIFY_ATTEMPTS + 1):
        attempt_prompt = (
            prompt
            if last_error is None
            else f"{prompt}\n\n{REPAIR_PROMPT.format(error=last_error)}"
        )
        completion = await _complete_with_retry(
            provider, context, attempt_prompt, schema, attempt
        )

        outcome = parse_triage_result(completion.raw)
        if outcome.ok and outcome.result is not None:
            return {
                "result": outcome.result.model_dump(mode="json"),
                "confidence": outcome.result.confidence,
            }
        last_error = outcome.error
        logger.warning("classify attempt %d rejected: %s", attempt, last_error)

    # Exhausted the repair retry — a typed failure, never a partial success.
    return {
        "result": None,
        "failure_reason": "schema_invalid",
        "error": last_error,
    }


async def ground_check(state: TriageState, config: RunnableConfig) -> TriageState:
    """Enforce the grounding rule in code (D9). No citation, no completion."""
    raw_result = state.get("result")
    if raw_result is None:
        return {}

    result = TriageResult.model_validate(raw_result)
    evidence = state.get("evidence", [])
    if not is_grounded(result, evidence):
        return {
            "failure_reason": "ungrounded",
            "error": (
                "no citation referenced a chunk retrieved in this run; "
                f"model supplied {len(result.citations)} citation(s)"
            ),
        }
    return {"citations": valid_citations(result, evidence)}


async def propose(state: TriageState, config: RunnableConfig) -> TriageState:
    """Final node for Phase 2 — the proposal is recorded, nothing is executed.

    Phase 3 inserts the durable interrupt directly after this node.
    """
    result = dict(state.get("result") or {})
    # requires_approval is derived, never taken from the model (spec 03 §5):
    # the proposed action is a write tool, and write tools are always gated.
    result["requires_approval"] = True
    result["citations"] = state.get("citations", [])
    return {"result": result}


def _after_classify(state: TriageState) -> str:
    return "failed" if state.get("failure_reason") else "ground_check"


def _after_ground_check(state: TriageState) -> str:
    return "failed" if state.get("failure_reason") else "propose"


def build_graph(checkpointer: Any | None = None) -> Any:
    graph = StateGraph(TriageState)
    graph.add_node("load_ticket", load_ticket)
    graph.add_node("retrieve_evidence", retrieve_evidence)
    graph.add_node("classify", classify)
    graph.add_node("ground_check", ground_check)
    graph.add_node("propose", propose)

    graph.set_entry_point("load_ticket")
    graph.add_edge("load_ticket", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "classify")
    graph.add_conditional_edges(
        "classify", _after_classify, {"ground_check": "ground_check", "failed": END}
    )
    graph.add_conditional_edges(
        "ground_check", _after_ground_check, {"propose": "propose", "failed": END}
    )
    graph.add_edge("propose", END)
    return graph.compile(checkpointer=checkpointer)
