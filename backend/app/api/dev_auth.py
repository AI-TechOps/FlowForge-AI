"""Local token issuance for development and CI. Never reachable in prod.

This is the offline stand-in for Auth0's `/oauth/token`, and it is the one
endpoint besides health that is legitimately unauthenticated — a login
endpoint cannot require a login. That makes it the sharpest edge in Phase 4,
so it carries three independent guards:

1. 404 when `APP_ENV=prod`.
2. 404 unless `AUTH_PROVIDER=local` — with Auth0 live there is nothing to
   issue, because we never mint tokens of our own (D18 decision 2).
3. It only signs for a user that already exists. There is no self-signup here
   any more than there is in the real flow; this picks an existing identity,
   it does not create one.

The tokens it returns are verified by exactly the same code that verifies an
Auth0 token (D18 decision 1) — this shortcuts *issuance*, never validation.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.provider import LocalDevProvider, get_auth_provider
from app.config import get_settings
from app.db import get_session
from app.models import User

router = APIRouter()


class DevTokenRequest(BaseModel):
    # Plain str, not EmailStr: the demo identities are `admin@demo` and friends,
    # which a strict RFC validator rejects for having no TLD. The value is only
    # ever an equality lookup against a seeded row.
    email: str = Field(min_length=1, max_length=320)
    # Emails are unique per organization, not globally. A gate proving the
    # tenant boundary needs a principal in each org, and if both fixtures use
    # the same address the email alone cannot say which. This selects *who is
    # logging in* — it is not an org override: once authenticated, the org
    # comes from the user row and no request field can change it.
    org_id: uuid.UUID | None = None


class DevTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def _guard() -> LocalDevProvider:
    settings = get_settings()
    if settings.app_env == "prod" or settings.auth_provider != "local":
        raise HTTPException(status_code=404, detail="not found")
    provider = get_auth_provider()
    if not isinstance(provider, LocalDevProvider):  # pragma: no cover - defensive
        raise HTTPException(status_code=404, detail="not found")
    return provider


@router.post("/api/dev/token", response_model=DevTokenResponse)
async def issue_dev_token(
    payload: DevTokenRequest,
    session: AsyncSession = Depends(get_session),
) -> DevTokenResponse:
    provider = _guard()
    settings = get_settings()

    query = select(User).where(User.email == payload.email)
    if payload.org_id is not None:
        query = query.where(User.org_id == payload.org_id)
    users = (await session.execute(query.limit(2))).scalars().all()

    if len(users) > 1:
        raise HTTPException(
            status_code=409,
            detail="email exists in more than one organization; pass org_id",
        )
    if not users:
        raise HTTPException(status_code=404, detail="no such user")

    user = users[0]
    # Stable per user, so a token survives a reseed and a restart links back to
    # the same row. First use flows through the same first-login linking path
    # an Auth0 subject would, rather than around it.
    subject = user.auth_subject or f"local|{user.id}"
    return DevTokenResponse(
        access_token=provider.issue(subject, user.email, settings.dev_token_ttl_seconds),
        expires_in=settings.dev_token_ttl_seconds,
    )
