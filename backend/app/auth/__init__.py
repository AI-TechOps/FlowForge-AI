"""Authentication and authorization (Phase 4).

`provider` verifies tokens; `principal` turns a verified token into the acting
human and enforces roles. Nothing outside this package names an identity
provider.
"""

from app.auth.provider import (
    AuthProvider,
    InvalidToken,
    LocalDevProvider,
    TokenClaims,
    bearer_token,
    get_auth_provider,
)

__all__ = [
    "AuthProvider",
    "InvalidToken",
    "LocalDevProvider",
    "TokenClaims",
    "bearer_token",
    "get_auth_provider",
]
