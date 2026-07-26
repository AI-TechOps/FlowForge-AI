import uuid

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Organization


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
