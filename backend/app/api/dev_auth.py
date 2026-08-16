"""Local token issuance for development and CI. Never reachable in prod.

This is the offline stand-in for Auth0's `/oauth/token`, and it is the one
endpoint besides health that is legitimately unauthenticated — a login endpoint
cannot require a login. That makes it the sharpest edge in Phase 4, so it
carries two hard guards:

1. 404 when `APP_ENV=prod`.
2. 404 unless `AUTH_PROVIDER=local` — with Auth0 live there is nothing to
   issue, because we never mint tokens of our own (D18 decision 2).

It deliberately signs for identities the application does not know. That reads
like a hole and is the opposite: this is a *test identity provider*, and a real
IdP will happily issue a valid token to someone with no FlowForge account. If
this endpoint refused unknown subjects, the refusal that actually protects the
system — first-login provisioning returning 403 for an identity we have no
account for (G4.1) — could never be exercised, because no valid token for such
an identity could exist. Authorisation is decided at `current_principal`
against our database, not here.

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

# An hour is plenty for a gate run, and it bounds how long a stray dev token
# stays useful if one escapes a terminal history.
MAX_TTL_SECONDS = 3600


class DevTokenRequest(BaseModel):
    # Plain str, not EmailStr: the demo identities are `admin@demo` and friends,
    # which a strict RFC validator rejects for having no TLD. The value only
    # ever becomes an `email` claim, which first-login linking matches against
    # a seeded row.
    email: str = Field(min_length=1, max_length=320)
    # The OIDC `sub`. Explicit rather than derived, because a caller proving
    # first-login behaviour needs to choose whether a subject is one we have
    # seen before.
    subject: str | None = Field(default=None, max_length=255)
    # Emails are unique per organization, not globally, so the same address can
    # exist in two tenants. This selects *who is logging in* when that happens;
    # it is not an org override — once authenticated the org comes from the user
    # row and no request field can change it.
    org_id: uuid.UUID | None = None
    expires_in_seconds: int | None = Field(default=None, ge=1, le=MAX_TTL_SECONDS)


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

    ttl = min(payload.expires_in_seconds or settings.dev_token_ttl_seconds, MAX_TTL_SECONDS)
    subject = payload.subject or await _stable_subject(session, payload)
    return DevTokenResponse(
        access_token=provider.issue(subject, payload.email, ttl),
        expires_in=ttl,
    )


async def _stable_subject(session: AsyncSession, payload: DevTokenRequest) -> str:
    """The same subject every time, for an identity we already know.

    A fresh random subject per call looked harmless and was not: first login
    binds it to the user, and the *second* login arrives as a different unknown
    subject for an address that is now claimed — which first-login provisioning
    correctly refuses. Signing in twice as the same seeded user returned 403,
    and no gate saw it because the suites mint one token per session and reuse
    it. An end-to-end run as a human does not.

    An unknown address still gets a random subject: that is a genuinely new
    identity, and the 403 it earns from provisioning is the behaviour under
    test, not a bug.
    """
    query = select(User).where(User.email == payload.email)
    if payload.org_id is not None:
        query = query.where(User.org_id == payload.org_id)
    users = (await session.execute(query.limit(2))).scalars().all()
    if len(users) != 1:
        return f"local|{uuid.uuid4()}"
    return users[0].auth_subject or f"local|{users[0].id}"
