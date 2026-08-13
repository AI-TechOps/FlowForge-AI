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

from app.api.deps import current_org_id
from app.config import get_settings
from app.integrations.ticket_system import clear_fault, recorded_calls, set_fault

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
    _org_id: uuid.UUID = Depends(current_org_id),
) -> dict[str, list[dict[str, Any]]]:
    """Every adapter call made for a run, in order.

    Includes reads: G3.5 needs to see the confirmation re-fetch, not just the
    write it confirms.
    """
    _guard()
    return {"calls": await recorded_calls(run_id)}


@router.post(f"{BASE}/failures", status_code=204)
async def inject_failure(
    payload: FaultIn,
    _org_id: uuid.UUID = Depends(current_org_id),
) -> None:
    """Arm the adapter to fail its next N calls.

    A counter rather than a flag so a gate can assert the retry policy exactly:
    arm two failures to exhaust the retries, or one to prove recovery.
    """
    _guard()
    await set_fault(payload.mode, payload.remaining_failures)


@router.delete(f"{BASE}/failures", status_code=204)
async def clear_failure(_org_id: uuid.UUID = Depends(current_org_id)) -> None:
    _guard()
    await clear_fault()
