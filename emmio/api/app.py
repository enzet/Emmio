"""Emmio HTTP API.

A thin FastAPI layer over the PostgreSQL storage in `emmio.postgres`. This is
the first, read-only slice: it exposes users and their courses and lexicons,
scoped by user, to prove the architecture end to end before authentication is
added.

For now the user is identified by a path parameter (`/users/{user_id}/...`).
Once authentication lands, the user will instead be derived from the request's
access token, and these routes will move under an authenticated `/me` prefix.

Run locally with:

    uvicorn emmio.api.app:app --reload
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from emmio import postgres

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

app: FastAPI = FastAPI(title="Emmio API", version="0.1")


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


def _require_user(user_id: str) -> None:
    """Raise 404 if the user does not exist."""

    if not postgres.user_exists(user_id):
        raise HTTPException(
            status_code=404, detail=f"Unknown user `{user_id}`."
        )


@app.get("/api/v1/users")
def get_users() -> list[User]:
    """List all users."""
    return [
        User(user_id=user_id, name=name)
        for user_id, name in postgres.list_users()
    ]


@app.get("/api/v1/users/{user_id}/courses")
def get_courses(user_id: str) -> list[Course]:
    """List a user's learning courses."""
    _require_user(user_id)
    return [
        Course(course_id=course_id, name=name, learning_language=language)
        for course_id, name, language in postgres.list_courses(user_id)
    ]


@app.get("/api/v1/users/{user_id}/lexicons")
def get_lexicons(user_id: str) -> list[Lexicon]:
    """List a user's lexicons."""
    _require_user(user_id)
    return [
        Lexicon(lexicon_id=lexicon_id, language=language)
        for lexicon_id, language in postgres.list_lexicons(user_id)
    ]
