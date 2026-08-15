import uuid

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Organization, User


async def current_org_id(
    session: AsyncSession = Depends(get_session),
    x_org_id: str | None = Header(default=None),
) -> uuid.UUID:
    """Resolve the acting organization.

    Phase 1-3 placeholder: an explicit X-Org-Id header (must exist), else the
    oldest org (the seeded demo org). Phase 4 replaces this with the org of
    the authenticated principal — client-supplied org ids are then ignored.
    """
    if x_org_id is not None:
        try:
            org_uuid = uuid.UUID(x_org_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid X-Org-Id") from exc
        org = await session.get(Organization, org_uuid)
        if org is None:
            raise HTTPException(status_code=404, detail="organization not found")
        return org.id

    result = await session.execute(
        select(Organization.id).order_by(Organization.created_at).limit(1)
    )
    org_id = result.scalar_one_or_none()
    if org_id is None:
        raise HTTPException(status_code=409, detail="no organization seeded; run scripts/seed.py")
    return org_id


async def current_user_id(
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(current_org_id),
    x_user_id: str | None = Header(default=None),
) -> uuid.UUID:
    """Resolve the acting human (D17 decision 3).

    Phase 3 placeholder mirroring `current_org_id`: an explicit X-User-Id that
    must name a real user in the acting org. Phase 4 replaces this with the
    authenticated principal plus the approver-role check, at which point the
    header is ignored entirely.

    Required rather than optional: an unattributed approval would make the
    audit trail meaningless in the very phase that exists to produce it.
    """
    if x_user_id is None:
        raise HTTPException(status_code=401, detail="X-User-Id is required to act as an approver")
    try:
        user_uuid = uuid.UUID(x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid X-User-Id") from exc

    user = await session.get(User, user_uuid)
    # Cross-org is "not found", never "forbidden" — consistent with the rest of
    # the tenant boundary, which must not confirm another org's rows exist.
    if user is None or user.org_id != org_id:
        raise HTTPException(status_code=404, detail="user not found")
    return user.id
