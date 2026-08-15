"""Auth provider abstraction (D18 decision 1): the ONLY module that knows
which identity provider is active.

Same shape as the LLM provider, and for the same reason. `Auth0Provider`
validates against a real tenant's JWKS; `LocalDevProvider` mints and validates
tokens from a keypair it persists beside the uploads volume, and the factory
refuses it when `APP_ENV=prod`.

The property that makes this safe is that **verification is one code path**.
`AuthProvider.verify` is concrete: same algorithm allow-list, same audience and
issuer checks, same expiry handling for both providers. A provider supplies a
key and nothing else. If verification ever forks per provider, the Phase 4
gates stop testing the code that ships — which is the entire objection to a
test-only auth bypass.
"""

import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# RS256 only. Deliberately an allow-list rather than trusting the token's own
# `alg` header: accepting whatever the token asks for is how the `alg: none`
# and HS256-signed-with-the-public-key confusions work.
ALGORITHMS = ["RS256"]

# Clock-drift tolerance, in seconds — and deliberately asymmetric.
#
# The two directions are not equally dangerous. Rejecting a token that has only
# just become valid (our clock trails the IdP's, so `iat`/`nbf` look like the
# future) is a retryable client annoyance. Accepting one that has *stopped*
# being valid is a security failure, and it is exactly what an attacker holding
# a leaked token needs.
#
# So a small tolerance covers the not-yet-valid side, and expiry is then
# re-checked with none at all. A single symmetric leeway would have made every
# token live that much past its stated `exp`, which is not what `exp` means.
LEEWAY_SECONDS = 5


class InvalidToken(Exception):
    """The bearer token is absent, malformed, expired, or not for us.

    Deliberately one exception for every failure mode. The caller turns this
    into a bare 401: telling an unauthenticated caller *why* verification
    failed helps an attacker far more than it helps a client.
    """


@dataclass(frozen=True)
class TokenClaims:
    """The only things we take from a token.

    Notably absent: roles. They come from `user_roles` in our database
    (D18 decision 3), so a revoked role takes effect on the next request
    rather than whenever the token happens to expire.
    """

    subject: str
    email: str | None
    expires_at: int


class AuthProvider(ABC):
    """Contract every identity provider implements."""

    issuer: str
    audience: str

    @abstractmethod
    def signing_key(self, token: str) -> Any:
        """Return the public key that should have signed `token`."""

    def verify(self, token: str) -> TokenClaims:
        """Validate a bearer token and return its claims.

        Concrete on purpose — see the module docstring. Subclasses choose the
        key; they do not choose the rules.
        """
        if not token:
            raise InvalidToken("no token presented")
        try:
            payload = jwt.decode(
                token,
                key=self.signing_key(token),
                algorithms=ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except Exception as exc:  # noqa: BLE001 - every failure is one 401
            raise InvalidToken(str(exc)) from exc

        # Expiry, re-checked with zero tolerance. `jwt.decode` applied the
        # leeway above to every time claim including `exp`; this takes it back
        # for the one claim where being generous is a vulnerability.
        if int(payload["exp"]) <= int(time.time()):
            raise InvalidToken("token has expired")

        subject = payload.get("sub")
        if not subject:
            raise InvalidToken("token has no subject")
        return TokenClaims(
            subject=str(subject),
            email=payload.get("email"),
            expires_at=int(payload["exp"]),
        )


def _generate_key() -> rsa.RSAPrivateKey:
    # 2048 is the floor for RS256 and the fastest to generate; this runs at
    # most once per container, not per request.
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _load_or_create_key(key_path: Path | None) -> rsa.RSAPrivateKey:
    if key_path is None:
        return _generate_key()
    try:
        if key_path.exists():
            loaded = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            if isinstance(loaded, rsa.RSAPrivateKey):
                return loaded
            logger.warning("dev issuer key at %s is not RSA; regenerating", key_path)

        key = _generate_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        key_path.chmod(0o600)
        return key
    except OSError:
        logger.warning(
            "dev issuer key at %s is unusable; falling back to an ephemeral key "
            "(tokens will not survive a restart)",
            key_path,
            exc_info=True,
        )
        return _generate_key()


class Auth0Provider(AuthProvider):
    """Validates access tokens issued by an Auth0 tenant (D18 decision 2).

    We issue no token of our own: this verifies Auth0's on every request
    against a cached JWKS. `PyJWKClient` handles the cache and the key
    rotation, refetching when a token arrives with an unseen `kid`.
    """

    def __init__(self, domain: str, audience: str) -> None:
        self.issuer = f"https://{domain}/"
        self.audience = audience
        self._jwks = jwt.PyJWKClient(
            f"https://{domain}/.well-known/jwks.json",
            cache_keys=True,
            lifespan=3600,
        )

    def signing_key(self, token: str) -> Any:
        try:
            return self._jwks.get_signing_key_from_jwt(token).key
        except Exception as exc:  # noqa: BLE001 - unknown kid is just a bad token
            raise InvalidToken("no signing key for this token") from exc


class LocalDevProvider(AuthProvider):
    """Offline issuer for development and CI. Refused in prod by the factory.

    Exists so G4.1-G4.6 can run with no Auth0 tenant reachable, while still
    exercising the real verification path: tokens are genuinely RS256-signed
    and genuinely verified, and a forged or expired one is rejected by exactly
    the code that rejects an Auth0 token.

    The keypair is persisted, deliberately. A per-process key looked tidier
    and was wrong: restarting the backend would then invalidate every
    outstanding token, and Auth0's keys plainly do not rotate because *we*
    restarted. Phase 3's durability gate restarts the backend mid-run on
    purpose, so a dev issuer that logged everyone out at that moment would be
    testing a behaviour production does not have.

    The key lives beside the uploads volume so it survives a container
    restart, is written 0600, and never enters the repository. If it cannot be
    read or written the issuer falls back to an ephemeral key: a dev login that
    works until the next restart beats one that will not start.
    """

    def __init__(self, audience: str, key_path: Path | None = None) -> None:
        self.issuer = "https://local.flowforge.test/"
        self.audience = audience
        self._private_key = _load_or_create_key(key_path)
        self._public_key = self._private_key.public_key()

    def signing_key(self, token: str) -> Any:
        del token
        return self._public_key

    def issue(self, subject: str, email: str | None, ttl_seconds: int) -> str:
        """Mint a token for an already-seeded subject.

        Callers must confirm the subject exists in our database first — this
        signs what it is given. See `app.api.dev_auth` for that check.
        """
        now = int(time.time())
        pem = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return jwt.encode(
            {
                "sub": subject,
                "email": email,
                "iss": self.issuer,
                "aud": self.audience,
                "iat": now,
                "exp": now + ttl_seconds,
                "jti": str(uuid.uuid4()),
            },
            key=pem,
            algorithm=ALGORITHMS[0],
        )


def get_auth_provider(settings: Settings | None = None) -> AuthProvider:
    """The one place that decides which identity provider is live.

    The default path is cached because both providers hold per-process state
    worth keeping: Auth0's JWKS cache, and the local issuer's keypair —
    rebuilding that per request would invalidate every token it just minted.
    An explicit `settings` bypasses the cache so a test can construct a
    provider for a configuration the process is not running under.
    """
    if settings is not None:
        return _build(settings)
    return _cached_provider()


@lru_cache
def _cached_provider() -> AuthProvider:
    return _build(get_settings())


def _build(settings: Settings) -> AuthProvider:
    if settings.auth_provider == "auth0":
        domain = (settings.auth0_domain or "").strip()
        audience = (settings.auth0_audience or "").strip()
        if not domain or not audience:
            raise ValueError(
                "AUTH_PROVIDER=auth0 requires AUTH0_DOMAIN and AUTH0_AUDIENCE to be set."
            )
        return Auth0Provider(domain, audience)

    if settings.app_env == "prod":
        raise ValueError("AUTH_PROVIDER=local is for dev/CI only, never prod.")
    # Beside the uploads volume, so it survives a container restart. See the
    # LocalDevProvider docstring for why that matters.
    return LocalDevProvider(
        settings.auth0_audience or "flowforge-api",
        Path(settings.upload_dir) / ".dev-issuer-key.pem",
    )


def bearer_token(header_value: str | None) -> str:
    """Pull the token out of an `Authorization: Bearer <token>` header."""
    if not header_value:
        raise InvalidToken("missing Authorization header")
    scheme, _, token = header_value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise InvalidToken("expected an Authorization: Bearer header")
    return token.strip()
