"""The acting human, and what they are allowed to do (spec 05 §2, §3).

Two rules hold everything else up:

1. **`org_id` comes from the principal, never from the request.** No header,
   query parameter, or body field can change which tenant a call acts in. The
   Phase 1-3 `X-Org-Id` / `X-User-Id` placeholders are gone.
2. **Roles come from `user_roles`, not from token claims** (D18 decision 3).
   The token says who; the database says what they may do, so revoking a role
   takes effect on the next request.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.provider import InvalidToken, bearer_token, get_auth_provider
from app.db import get_session
from app.models import Role, User

# A 401 must say how to authenticate, per RFC 6750, and must not say why
# verification failed — that only helps whoever is guessing.
UNAUTHENTICATED = HTTPException(
    status_code=401,
    detail="not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


@dataclass(frozen=True)
class Principal:
    """One authenticated human. Frozen: nothing downstream may re-target it."""

    user_id: uuid.UUID
    org_id: uuid.UUID
    email: str
    subject: str
    roles: frozenset[Role]

    def has_any(self, *roles: Role) -> bool:
        return bool(self.roles.intersection(roles))


async def current_principal(
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> Principal:
    """Resolve the authenticated human from the bearer token.

    First-login provisioning (spec 05 §1): a subject we have never seen is
    linked to a seeded user with the same email. If no such user exists the
    answer is 403, not a new account — the MVP has no self-signup, and an
    unrecognised identity from a valid token is a real principal we simply do
    not know, which is exactly the case 403 describes.
    """
    try:
        claims = get_auth_provider().verify(bearer_token(authorization))
    except InvalidToken as exc:
        raise UNAUTHENTICATED from exc

    user = (
        await session.execute(
            select(User)
            .where(User.auth_subject == claims.subject)
            .options(selectinload(User.roles))
        )
    ).scalar_one_or_none()

    if user is None:
        user = await _link_first_login(session, claims.subject, claims.email)

    return Principal(
        user_id=user.id,
        org_id=user.org_id,
        email=user.email,
        subject=claims.subject,
        roles=frozenset(grant.role for grant in user.roles),
    )


async def _link_first_login(session: AsyncSession, subject: str, email: str | None) -> User:
    """Bind an Auth0 subject to the seeded user with a matching email."""
    if not email:
        # A token with no email claim can never be matched to a seeded user,
        # so there is nothing to link and no account to create.
        raise HTTPException(status_code=403, detail="no FlowForge account for this identity")

    # Emails are unique per organization, not globally (uq_users_org_email), so
    # the same address can exist in two tenants. Linking would then have to
    # guess which org the login belongs to, and a wrong guess hands one
    # tenant's data to another's user. Refuse instead: fetching two rows is
    # enough to detect the ambiguity.
    candidates = (
        (
            await session.execute(
                select(User)
                .where(User.email == email, User.auth_subject.is_(None))
                .options(selectinload(User.roles))
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    if len(candidates) != 1:
        raise HTTPException(status_code=403, detail="no FlowForge account for this identity")
    user = candidates[0]

    user.auth_subject = subject
    await session.commit()
    await session.refresh(user, ["roles"])
    return user


def require_roles(*allowed: Role) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory enforcing one row of the spec 05 §2 matrix.

    403 rather than 404 here: the caller is authenticated and the resource
    exists, they simply may not do this. The 404-not-403 rule is about the
    *tenant* boundary — never confirming another org's rows exist — and is
    enforced by the org scoping, not by this check.
    """

    async def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.has_any(*allowed):
            raise HTTPException(
                status_code=403,
                detail=f"requires one of: {', '.join(sorted(r.value for r in allowed))}",
            )
        return principal

    return dependency


async def current_org_id(principal: Principal = Depends(current_principal)) -> uuid.UUID:
    """Compatibility shim for handlers that only need the tenant.

    Same name as the Phase 1-3 header placeholder it replaces, so the call
    sites read identically — but the value now comes from a verified token and
    there is no request field that can influence it.
    """
    return principal.org_id
