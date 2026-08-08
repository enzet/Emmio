"""Authentication helpers for the Emmio API.

Two independent pieces:

- Password hashing with bcrypt. Passwords are never stored; only a one-way
  hash is kept, and login re-hashes the candidate and compares.
- Stateless access tokens (JWT). After a correct login the server issues a
  signed token carrying the user login in its `sub` claim. Later requests
  present the token, and the server verifies the signature with its secret
  instead of asking for the password again.

The signing secret comes from the `EMMIO_JWT_SECRET` environment variable. The
development default is insecure; with `EMMIO_ENV=production` (set this in any
real deployment) an unset secret is a startup error instead of a silent
fallback, since anyone who knows the default could forge access tokens.
"""

import os
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

_DEV_SECRET: str = "dev-secret-do-not-use"  # noqa: S105 -- not a real secret
_configured_secret: str | None = os.environ.get("EMMIO_JWT_SECRET")

if _configured_secret is None and os.environ.get("EMMIO_ENV") == "production":
    msg = (
        "EMMIO_JWT_SECRET is unset with EMMIO_ENV=production. Refusing to "
        "start with the public dev default, which would let anyone forge "
        "access tokens."
    )
    raise RuntimeError(msg)

_SECRET: str = _configured_secret or _DEV_SECRET
_ALGORITHM: str = "HS256"
ACCESS_TOKEN_TTL: timedelta = timedelta(hours=1)
REMEMBER_TOKEN_TTL: timedelta = timedelta(days=7)
"""Longer token lifetime when the user ticks "remember me" at login."""


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Check a plaintext password against a stored hash."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: str, ttl: timedelta | None = None) -> str:
    """Create a signed access token carrying the user login.

    :param user_id: user login to embed in the token's `sub` claim
    :param ttl: how long the token stays valid; defaults to `ACCESS_TOKEN_TTL`
    """
    payload: dict[str, object] = {
        "sub": user_id,
        "exp": datetime.now(UTC) + (ttl or ACCESS_TOKEN_TTL),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> str:
    """Verify a token and return the user login from its `sub` claim.

    :raises jwt.InvalidTokenError: if the token is invalid or expired
    """
    payload: dict[str, object] = jwt.decode(
        token, _SECRET, algorithms=[_ALGORITHM]
    )
    return str(payload["sub"])
