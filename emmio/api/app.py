"""Emmio HTTP API.

A thin FastAPI layer over the PostgreSQL storage in `emmio.postgres`.

Authentication: register with email and password, then log in to receive a
signed access token. Authenticated routes live under `/me` and derive the
current user from that token, so a client can only reach its own data. See
`emmio.api.auth` for the hashing and token details.

Run locally with:

    uvicorn emmio.api.app:app --reload
"""

from typing import Annotated

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

from emmio import postgres
from emmio.api import auth

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

app: FastAPI = FastAPI(title="Emmio API", version="0.1")

# Tells clients (and `/docs`) where to obtain a token, and extracts the bearer
# token from the `Authorization` header on protected routes.
oauth2_scheme: OAuth2PasswordBearer = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login"
)


class User(BaseModel):
    """A user account."""

    user_id: str
    name: str


class Course(BaseModel):
    """A learning course owned by a user."""

    course_id: str
    name: str
    learning_language: str


class Lexicon(BaseModel):
    """A lexicon owned by a user."""

    lexicon_id: str
    language: str


class RegisterRequest(BaseModel):
    """Registration payload."""

    user_id: str
    name: str
    email: str
    password: str


class Token(BaseModel):
    """An issued access token."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105  # Not a password.


def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    """Resolve the current user's login from the bearer token.

    Used as a dependency on protected routes; raises 401 if the token is
    missing, malformed, or expired.
    """
    try:
        return auth.decode_access_token(token)
    except jwt.InvalidTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


@app.post("/api/v1/auth/register", status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest) -> User:
    """Create a new account with login credentials."""
    try:
        postgres.register_user(
            request.user_id,
            request.name,
            request.email,
            auth.hash_password(request.password),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    return User(user_id=request.user_id, name=request.name)


@app.post("/api/v1/auth/login")
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
    """Log in with email (as `username`) and password, returning a token."""
    credentials: tuple[str, str] | None = postgres.get_credentials_by_email(
        form.username
    )
    if credentials is None or not auth.verify_password(
        form.password, credentials[1]
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=auth.create_access_token(credentials[0]))


@app.get("/api/v1/me/courses")
def get_my_courses(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[Course]:
    """List the authenticated user's learning courses."""
    return [
        Course(course_id=course_id, name=name, learning_language=language)
        for course_id, name, language in postgres.list_courses(user_id)
    ]


@app.get("/api/v1/me/lexicons")
def get_my_lexicons(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[Lexicon]:
    """List the authenticated user's lexicons."""
    return [
        Lexicon(lexicon_id=lexicon_id, language=language)
        for lexicon_id, language in postgres.list_lexicons(user_id)
    ]
