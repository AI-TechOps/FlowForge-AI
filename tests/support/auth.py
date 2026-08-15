"""Bearer tokens for the Phase 0-3 gate suites, which predate authentication.

Phase 4 made `org_id` a property of the authenticated principal (D18), so the
`X-Org-Id` header those suites relied on no longer selects a tenant — nothing
does, from outside a token. Rather than rewrite three suites, this maps the
thing they already have (an org id) onto the thing the API now wants (a token
for a user in that org).

Deliberately harness-only: not one assertion in those suites changed. They
still prove exactly what they proved before, through a front door that is now
locked. A gate that had to be weakened to survive authentication would be a
gate worth keeping red.

The synthetic user holds all three roles, because these suites cross persona
boundaries freely — Phase 1 uploads documents (administrator) and Phase 3 files
tickets and approves them. Splitting them by role would be re-litigating the
Phase 4 matrix inside suites that are not testing it; G4.2 owns that question
and asserts it per endpoint.
"""

from __future__ import annotations

import asyncio
import json
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

ROLES = ("administrator", "operator", "approver")

# One token per (base_url, org_id) for the whole session. Minting is a database
# write plus an HTTP round trip, and these suites call the API hundreds of
# times.
_TOKENS: dict[tuple[str, str], str] = {}


def asyncpg_url(database_url: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(
        ("postgresql", parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )


async def _ensure_user(database_url: str, org_id: str, email: str) -> None:
    import asyncpg

    connection = await asyncpg.connect(asyncpg_url(database_url))
    try:
        user_id = uuid4()
        await connection.execute(
            "INSERT INTO users (id, org_id, email, auth_subject) VALUES ($1, $2, $3, NULL)",
            user_id,
            UUID(org_id),
            email,
        )
        for role in ROLES:
            await connection.execute(
                "INSERT INTO user_roles (user_id, role) VALUES ($1, $2)",
                user_id,
                role,
            )
    finally:
        await connection.close()


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(
            f"local dev token issuance failed ({exc.code}) at {url}: {detail}"
        ) from exc


def gate_database_url() -> str:
    """The database these suites seed against.

    Read here rather than threaded through three client constructors: each
    suite already exports its own PHASE*_DATABASE_URL, and this keeps the
    retrofit to one line inside each `request()`.
    """
    for name in (
        "PHASE1_DATABASE_URL",
        "PHASE2_DATABASE_URL",
        "PHASE3_DATABASE_URL",
        "PHASE4_DATABASE_URL",
        "DATABASE_URL",
    ):
        value = os.environ.get(name)
        if value:
            return value
    raise AssertionError(
        "a PHASE*_DATABASE_URL or DATABASE_URL is required to mint gate tokens"
    )


def token_for_org(base_url: str, database_url: str, org_id: str) -> str:
    """Return a bearer token for a full-persona user in `org_id`.

    Creates the user on first use. The subject is left NULL so the token's
    subject binds through the same first-login path a real Auth0 login takes,
    rather than around it.
    """
    key = (base_url.rstrip("/"), org_id)
    cached = _TOKENS.get(key)
    if cached is not None:
        return cached

    email = f"gate-{org_id[:8]}-{uuid4().hex[:8]}@gates.test"
    asyncio.run(_ensure_user(database_url, org_id, email))
    body = _post_json(
        f"{base_url.rstrip('/')}/api/dev/token",
        {"email": email, "subject": f"gate|{uuid4()}"},
    )
    token = body.get("access_token")
    assert isinstance(token, str) and token, (
        f"dev issuer returned no access_token: {body!r}"
    )
    _TOKENS[key] = token
    return token


async def _email_for_user(database_url: str, user_id: str) -> str:
    import asyncpg

    connection = await asyncpg.connect(asyncpg_url(database_url))
    try:
        email = await connection.fetchval(
            "SELECT email FROM users WHERE id = $1", UUID(user_id)
        )
    finally:
        await connection.close()
    assert email, f"no seeded user {user_id} to mint a token for"
    return str(email)


def token_for_user(base_url: str, database_url: str, user_id: str) -> str:
    """Return a bearer token that authenticates as one specific seeded user.

    Phase 3 names its approvers by id and then asserts the decision was
    attributed to them. Minting per user rather than per org keeps those
    assertions intact: attribution still lands on the human the test chose, now
    established by the token instead of by a header the caller could set to
    anyone.
    """
    key = (base_url.rstrip("/"), f"user:{user_id}")
    cached = _TOKENS.get(key)
    if cached is not None:
        return cached

    email = asyncio.run(_email_for_user(database_url, user_id))
    body = _post_json(
        f"{base_url.rstrip('/')}/api/dev/token",
        {"email": email, "subject": f"gate-user|{user_id}"},
    )
    token = body.get("access_token")
    assert isinstance(token, str) and token, (
        f"dev issuer returned no access_token: {body!r}"
    )
    _TOKENS[key] = token
    return token
