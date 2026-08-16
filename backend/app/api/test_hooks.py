"""Dev-only inspection and fault-injection hooks for the mock ticket system.

Spec 04 §2 requires the mock to expose a call recorder and injectable failures
so G3.2 and G3.6 can be proven rather than assumed. Those controls have to be
reachable over HTTP because the gates drive the product's real API and restart
the stack mid-run — an in-process recorder is invisible to them.

Deliberately NOT product APIs: every route here 404s when `APP_ENV=prod`, the
same guard the dev-only retrieve endpoint uses. They read and clear
test-support state in Redis and can neither create nor modify tickets.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import ADMIN_ONLY, Principal
from app.config import get_settings
from app.db import get_session
from app.integrations.ticket_system import clear_fault, recorded_calls, set_fault
from app.models import Run
from app.tenancy import get_scoped

router = APIRouter()

BASE = "/api/test/mock-ticket-system"


def _guard() -> None:
    if get_settings().app_env == "prod":
        raise HTTPException(status_code=404, detail="not found")


class FaultIn(BaseModel):
    mode: str = Field(pattern="^(timeout|error)$")
    remaining_failures: int = Field(default=1, ge=1, le=1000)


@router.get(f"{BASE}/calls")
async def list_adapter_calls(
    run_id: uuid.UUID = Query(...),
    principal: Principal = ADMIN_ONLY,
    session: AsyncSession = Depends(get_session),
) -> dict[str, list[dict[str, Any]]]:
    """Every adapter call made for a run, in order.

    Includes reads: G3.5 needs to see the confirmation re-fetch, not just the
    write it confirms.

    The run is resolved under the acting organization first. The Redis key is
    keyed only by run id, so without this check one tenant could read another's
    write trace — ticket ids, teams, priorities, note bodies. The endpoint is
    dev-only, but D7's tenant boundary should hold in shared dev and CI too.
    """
    _guard()
    run = await get_scoped(session, Run, run_id, principal.org_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"calls": await recorded_calls(run_id)}


@router.post(f"{BASE}/failures", status_code=204)
async def inject_failure(
    payload: FaultIn,
    _principal: Principal = ADMIN_ONLY,
) -> None:
    """Arm the adapter to fail its next N calls.

    A counter rather than a flag so a gate can assert the retry policy exactly:
    arm two failures to exhaust the retries, or one to prove recovery.
    """
    _guard()
    await set_fault(payload.mode, payload.remaining_failures)


@router.delete(f"{BASE}/failures", status_code=204)
async def clear_failure(_principal: Principal = ADMIN_ONLY) -> None:
    _guard()
    await clear_fault()
