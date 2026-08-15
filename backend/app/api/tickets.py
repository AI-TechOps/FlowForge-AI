import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import ANY_PERSONA, OPERATOR_WORK, Principal
from app.db import get_session
from app.models import Ticket, TicketStatus

router = APIRouter()


class TicketCreate(BaseModel):
    """The New Ticket form (MVP spec step 2). Limits enforced server-side."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10_000)
    department: str | None = Field(default=None, max_length=100)
    service: str | None = Field(default=None, max_length=100)
    priority: str | None = Field(default=None, max_length=10)
    created_by: str | None = Field(default=None, max_length=320)


def ticket_payload(ticket: Ticket) -> dict[str, Any]:
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
        "is_eval_seed": ticket.is_eval_seed,
        "created_by": ticket.created_by,
        "created_at": ticket.created_at.isoformat(),
    }


@router.post("/api/tickets", status_code=201)
async def create_ticket(
    payload: TicketCreate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = OPERATOR_WORK,
) -> dict[str, Any]:
    # org_id comes from the token and nowhere else. TicketCreate has no org_id
    # field, so an org_id in the body is dropped by the model rather than
    # honoured -- the tenant of a new ticket is never client-controlled (G4.5).
    ticket = Ticket(org_id=principal.org_id, status=TicketStatus.new, **payload.model_dump())
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket_payload(ticket)


@router.get("/api/tickets")
async def list_tickets(
    session: AsyncSession = Depends(get_session),
    principal: Principal = ANY_PERSONA,
    status: TicketStatus | None = Query(default=None),
    department: str | None = Query(default=None),
    service: str | None = Query(default=None),
    is_eval_seed: bool | None = Query(default=None),
) -> list[dict[str, Any]]:
    statement = select(Ticket).where(Ticket.org_id == principal.org_id)
    if status is not None:
        statement = statement.where(Ticket.status == status)
    if department is not None:
        statement = statement.where(Ticket.department == department)
    if service is not None:
        statement = statement.where(Ticket.service == service)
    if is_eval_seed is not None:
        statement = statement.where(Ticket.is_eval_seed == is_eval_seed)

    tickets = (await session.execute(statement.order_by(Ticket.created_at.desc()))).scalars().all()
    return [ticket_payload(ticket) for ticket in tickets]


@router.get("/api/tickets/{ticket_id}")
async def get_ticket_detail(
    ticket_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: Principal = ANY_PERSONA,
) -> dict[str, Any]:
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None or ticket.org_id != principal.org_id:
        raise HTTPException(status_code=404, detail="ticket not found")
    return ticket_payload(ticket)
