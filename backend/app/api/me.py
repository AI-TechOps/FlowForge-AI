"""Identity of the authenticated principal (spec 05 §1).

Powers the Phase 6 login screen's identity display and the frontend route
guards: the client asks "who am I and what may I do" once, rather than
inferring roles from which requests happen to 403.
"""

import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.auth.principal import Principal, current_principal

router = APIRouter()


class MeResponse(BaseModel):
    # `id`, not `user_id`: this resource *is* the user, so it names itself the
    # way every other resource in the API does.
    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    roles: list[str]


@router.get("/api/me", response_model=MeResponse)
async def read_me(principal: Principal = Depends(current_principal)) -> MeResponse:
    """Describes the caller, so it needs no role — only a valid token.

    Deliberately not role-gated: a principal holding no persona still has to be
    able to learn that, or the UI has no way to explain why everything else
    403s.
    """
    return MeResponse(
        id=principal.user_id,
        org_id=principal.org_id,
        email=principal.email,
        # Sorted so the response is stable for snapshot-style assertions and
        # for a UI that renders the list directly.
        roles=sorted(role.value for role in principal.roles),
    )


@router.post("/api/logout", status_code=204)
async def logout(principal: Principal = Depends(current_principal)) -> Response:
    """End the session client-side.

    There is deliberately nothing to revoke server-side: we issue no token of
    our own (D18 decision 2), so a session ends when the client discards the
    Auth0 token and it expires. Saying so explicitly is better than an endpoint
    that implies a revocation it cannot perform — a caller who keeps using the
    token stays authenticated until `exp`, and pretending otherwise would be
    the security claim we could not honour.

    Authenticated on purpose: an unauthenticated logout is a free probe for
    whether a token is still valid.
    """
    del principal
    return Response(status_code=204)
