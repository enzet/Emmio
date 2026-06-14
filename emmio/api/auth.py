"""Authentication helpers for the Emmio API.

Two independent pieces:

- Password hashing with bcrypt. Passwords are never stored; only a one-way
  hash is kept, and login re-hashes the candidate and compares.
- Stateless access tokens (JWT). After a correct login the server issues a
  signed token carrying the user login in its `sub` claim. Later requests
  present the token, and the server verifies the signature with its secret
  instead of asking for the password again.

The signing secret comes from the `EMMIO_JWT_SECRET` environment variable. The
development default is insecure and must be overridden in production.
"""

import os
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

_SECRET: str = os.environ.get("EMMIO_JWT_SECRET", "dev-secret-do-not-use")
_ALGORITHM: str = "HS256"
ACCESS_TOKEN_TTL: timedelta = timedelta(hours=1)


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Check a plaintext password against a stored hash."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: str) -> str:
    """Create a signed access token carrying the user login.

    :param user_id: user login to embed in the token's `sub` claim
    """
    payload: dict[str, object] = {
        "sub": user_id,
        "exp": datetime.now(UTC) + ACCESS_TOKEN_TTL,
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
