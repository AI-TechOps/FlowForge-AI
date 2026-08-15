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
    provider = get_auth_provider()
    token = None
    try:
        token = bearer_token(authorization)
        claims = provider.verify(token)
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
        email, verified = claims.email, claims.email_verified
        if not email:
            # An access token for a custom API carries authorization data, not
            # profile data — Auth0 puts `email` in the ID token, which the
            # frontend never sends us. Ask the provider directly. Only ever
            # reached once per user, at first login.
            email, verified = await provider.userinfo(token)
        if not verified:
            # The IdP will not vouch for this address. Linking anyway would let
            # someone who registers your email there claim your FlowForge user.
            raise HTTPException(status_code=403, detail="no FlowForge account for this identity")
        user = await _link_first_login(session, claims.subject, email)

    return Principal(
        user_id=user.id,
        org_id=user.org_id,
        email=user.email,
        subject=claims.subject,
        roles=frozenset(grant.role for grant in user.roles),
    )


async def _link_first_login(session: AsyncSession, subject: str, email: str | None) -> User:
    """Bind an identity provider subject to the seeded user with that email."""
    if not email:
        # No email claim, nothing to match on. `AuthProvider.identity` has
        # already tried the provider's own userinfo endpoint by this point, so
        # this really is an identity we cannot place.
        raise HTTPException(status_code=403, detail="no FlowForge account for this identity")

    # Emails are unique per organization, not globally (uq_users_org_email), so
    # the same address can exist in two tenants. Linking would then have to
    # guess which org the login belongs to, and a wrong guess hands one
    # tenant's data to another tenant's user. Refuse instead.
    #
    # Every row with this address counts, linked or not. Filtering to unlinked
    # rows looked like "find the one still waiting to be claimed" and was a
    # hole: with org A's row already linked, an unlinked org B row with the
    # same address became the *only* candidate, so a second subject silently
    # bound to a different tenant — the multi-org login that is explicitly out
    # of scope (Codex Phase 4 finding 5).
    candidates = (
        (
            await session.execute(
                select(User).where(User.email == email).options(selectinload(User.roles)).limit(2)
            )
        )
        .scalars()
        .all()
    )
    if len(candidates) != 1:
        raise HTTPException(status_code=403, detail="no FlowForge account for this identity")

    user = candidates[0]
    if user.auth_subject is not None:
        # Claimed by a different subject. Re-binding would let anyone who can
        # get the provider to assert this address take over the account.
        raise HTTPException(status_code=403, detail="no FlowForge account for this identity")

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


# The spec 05 §2 matrix, expressed once. Handlers depend on these rather than
# spelling out role tuples, so the matrix lives in one place and a reviewer can
# read a router's permissions off its imports.
#
# ADMIN_ONLY covers knowledge management and the dev-only routes: uploading a
# policy document and reading run traces are both administrator work.
ADMIN_ONLY = Depends(require_roles(Role.administrator))
# Filing a ticket and starting a triage run — the operator's job, and an
# administrator may do it too (personas doc).
OPERATOR_WORK = Depends(require_roles(Role.administrator, Role.operator))
# Reading tickets and runs. Everyone with a persona sees the work in flight;
# tenant scoping, not role, is what keeps it to their own organization.
ANY_PERSONA = Depends(require_roles(Role.administrator, Role.operator, Role.approver))
# The approval inbox. An administrator may look; only an approver may decide.
APPROVAL_READERS = Depends(require_roles(Role.administrator, Role.approver))
# The decision itself. Approver ONLY — deliberately excluding administrator
# (D18 decision 4): administrator is a configuration role, and letting it
# approve would put one principal on both sides of D4/D5 segregation of duties.
APPROVER_ONLY = Depends(require_roles(Role.approver))
