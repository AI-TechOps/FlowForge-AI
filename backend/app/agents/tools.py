"""Tool registry — the only actions the agent can take.

The contract here is deliberately fuller than Phase 2 needs, because Phase 3's
write tools reuse it unchanged: typed Pydantic arguments, injected org/user
context, a permission check, and an audit wrapper around every invocation.

Phase 2 ships the two auto-executing read tools. `requires_approval` is a
property of the tool, not of model output — that is what makes the Phase 3
gating trustworthy (spec 03 §5).
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import audit
from app.models import Ticket
from app.rag.retrieve import MAX_K, retrieve

ArgsT = TypeVar("ArgsT", bound=BaseModel)


@dataclass(frozen=True)
class ToolContext:
    """Who is acting, on behalf of which org, inside which run.

    org_id is never taken from model output or client input — it comes from
    the run (Phase 4 will source it from the authenticated principal).
    """

    session: AsyncSession
    org_id: uuid.UUID
    run_id: uuid.UUID | None = None
    actor: str = "agent"


class ToolPermissionError(RuntimeError):
    """Raised when the acting context may not invoke the tool."""


@dataclass(frozen=True)
class Tool(Generic[ArgsT]):
    name: str
    description: str
    args_model: type[ArgsT]
    handler: Callable[[ToolContext, ArgsT], Awaitable[Any]]
    requires_approval: bool = False
    permission_check: Callable[[ToolContext, ArgsT], None] | None = field(default=None)

    async def invoke(self, context: ToolContext, raw_args: dict[str, Any]) -> Any:
        """Audit, then validate, permission-check, and execute.

        The audit wrapper goes outermost so a rejected call is still a recorded
        call: argument validation and permission denials used to happen before
        the wrapper opened and left no trace at all (Codex Phase 2 finding 4).
        An unaudited authorization failure is the wrong default anywhere, and
        becomes a real hole in Phase 3 when write tools gate on that check.

        Payload is the raw arguments — the validated model does not exist yet
        when validation is what failed.
        """
        async with audit.timed(
            org_id=context.org_id,
            run_id=context.run_id,
            actor=context.actor,
            tool=self.name,
            payload=raw_args,
        ) as box:
            args = self.args_model.model_validate(raw_args)
            if self.permission_check is not None:
                self.permission_check(context, args)
            result = await self.handler(context, args)
            box["result"] = _summarize(result)
            return result


def _summarize(result: Any) -> Any:
    """Audit-friendly view of a tool result (full text lives in the run)."""
    if isinstance(result, list):
        return {"count": len(result), "items": result[:10]}
    return result


# --- search_company_knowledge -------------------------------------------------


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    k: int = 5

    @field_validator("k")
    @classmethod
    def _clamp_k(cls, value: int) -> int:
        """Clamp, don't reject (spec 03 §4).

        `le=MAX_K` made an over-large k a validation error. The spec says k is
        clamped server-side "regardless of what the model asks for" — a model
        asking for 100 should get 20, not blow up the run (Codex Phase 2
        finding 6). The deterministic graph always passes 5, so this is about
        the tool contract Phase 3 reuses.
        """
        return max(1, min(value, MAX_K))


async def _search_company_knowledge(context: ToolContext, args: SearchArgs) -> list[dict[str, Any]]:
    chunks = await retrieve(context.session, context.org_id, args.query, args.k)
    return [
        {
            "chunk_id": str(chunk.chunk_id),
            "score": round(chunk.score, 4),
            "text": chunk.text,
            "document_id": str(chunk.document_id),
            "document_title": chunk.document_title,
            "document_version": chunk.document_version,
            "page": chunk.page,
            "section": chunk.section,
        }
        for chunk in chunks
    ]


search_company_knowledge = Tool(
    name="search_company_knowledge",
    description="Search indexed company documentation; returns ranked, citable chunks.",
    args_model=SearchArgs,
    handler=_search_company_knowledge,
    requires_approval=False,
)


# --- get_ticket ---------------------------------------------------------------


class GetTicketArgs(BaseModel):
    ticket_id: uuid.UUID


async def _get_ticket(context: ToolContext, args: GetTicketArgs) -> dict[str, Any]:
    ticket = await context.session.get(Ticket, args.ticket_id)
    # Cross-org reads fail as "not found" rather than "forbidden" so the tool
    # never confirms the existence of another tenant's ticket (G2.6).
    if ticket is None or ticket.org_id != context.org_id:
        raise ToolPermissionError(f"ticket {args.ticket_id} not found")
    return {
        "id": str(ticket.id),
        "title": ticket.title,
        "description": ticket.description,
        "department": ticket.department,
        "service": ticket.service,
        "priority": ticket.priority,
        "assigned_team": ticket.assigned_team,
        "internal_notes": ticket.internal_notes,
        "status": ticket.status.value,
        "external_ref": ticket.external_ref,
    }


get_ticket = Tool(
    name="get_ticket",
    description="Read a ticket in the acting organization.",
    args_model=GetTicketArgs,
    handler=_get_ticket,
    requires_approval=False,
)


REGISTRY: dict[str, Tool[Any]] = {
    search_company_knowledge.name: search_company_knowledge,
    get_ticket.name: get_ticket,
}


def get_tool(name: str) -> Tool[Any]:
    try:
        return REGISTRY[name]
    except KeyError as exc:
        # The agent cannot act outside the registry — an unknown name is a
        # programming error, not something to improvise around.
        raise KeyError(f"unknown tool: {name}") from exc
