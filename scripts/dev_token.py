"""Fetch a bearer token from the local dev issuer, for scripts and for curl.

Phase 4 made every /api route require authentication, so the operational
scripts in this directory need a token the same way a browser does. This is the
one place they get it, rather than four copies of the same request.

Only works against the local issuer (dev/CI). Pointed at a stack running
AUTH_PROVIDER=auth0 the endpoint 404s, which is the intended answer: a real
deployment has a real login.

Usable directly, which is the point when reaching for curl:

    TOKEN=$(python scripts/dev_token.py --email admin@demo)
    curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/documents
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_EMAIL = "demo@demo"


def fetch_token(base_url: str = DEFAULT_BASE_URL, email: str = DEFAULT_EMAIL) -> str:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/dev/token",
        data=json.dumps({"email": email}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return str(json.load(response)["access_token"])
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SystemExit(
                "the local dev issuer is not available: this stack is either "
                "APP_ENV=prod or running AUTH_PROVIDER=auth0, where tokens come "
                "from Auth0 instead"
            ) from exc
        raise SystemExit(
            f"token request failed ({exc.code}): {exc.read().decode()}"
        ) from exc


def auth_header(
    base_url: str = DEFAULT_BASE_URL, email: str = DEFAULT_EMAIL
) -> dict[str, str]:
    return {"Authorization": f"Bearer {fetch_token(base_url, email)}"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--email",
        default=DEFAULT_EMAIL,
        help="Seeded user to authenticate as. Defaults to the all-roles demo user.",
    )
    arguments = parser.parse_args()
    print(fetch_token(arguments.base_url, arguments.email))
