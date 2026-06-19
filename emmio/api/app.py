"""Emmio HTTP API.

A thin FastAPI layer over the PostgreSQL storage in `emmio.postgres`.

Authentication: register with email and password, then log in to receive a
signed access token. Authenticated routes live under `/me` and derive the
current user from that token, so a client can only reach its own data. See
`emmio.api.auth` for the hashing and token details.

Run locally with:

    uvicorn emmio.api.app:app --reload
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from emmio import postgres
from emmio.api import auth
from emmio.api.render import elements_to_html
from emmio.data import Data
from emmio.dictionary.config import DictionaryUsageConfig
from emmio.language import KnownLanguages, Language
from emmio.lexicon.core import LexiconResponse, select_next_word
from emmio.lists.config import ListUsageConfig
from emmio.ui import Element

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
    """A lexicon owned by a user, with short info."""

    lexicon_id: str
    language: str
    selection: str | None
    words: int  # Number of words checked so far.


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
        Lexicon(
            lexicon_id=lexicon_id,
            language=language,
            selection=selection,
            words=words,
        )
        for lexicon_id, language, selection, words in postgres.list_lexicons(
            user_id
        )
    ]


class NextWord(BaseModel):
    """The next word to check, or `None` when the list is exhausted."""

    word: str | None


class Translation(BaseModel):
    """A word's translation as a safe HTML fragment, or `None` if not found."""

    word: str
    translation: str | None


# Languages the API returns definitions/translations in (matches the CLI).
_DEFINITION_LANGUAGES: list[Language] = [
    KnownLanguages.ENGLISH,
    KnownLanguages.RUSSIAN,
]


class AnswerRequest(BaseModel):
    """A user's answer to a checked word."""

    word: str
    response: str  # A `LexiconResponse` value, e.g. `know` or `dont`.


_data: Data | None = None


def get_data() -> Data:
    """Get the shared read-only data (frequency lists, dictionaries).

    Loaded once from the Emmio data directory (`EMMIO_DATA_DIR`, default
    `~/.emmio`). User-specific data comes from PostgreSQL instead.
    """
    global _data  # noqa: PLW0603  # pylint: disable=global-statement

    if _data is None:
        path: Path = Path(
            os.environ.get("EMMIO_DATA_DIR", str(Path.home() / ".emmio"))
        )
        _data = Data.from_directory(path)
    return _data


def _lexicon_config_or_404(user_id: str, lexicon_id: str) -> dict:
    """Get a lexicon's reassembled config dict or raise 404."""

    config: dict | None = postgres.get_lexicon_config(user_id, lexicon_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown lexicon `{lexicon_id}`.",
        )
    return config


@app.get("/api/v1/me/lexicons/{lexicon_id}/next")
def get_next_lexicon_word(
    lexicon_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> NextWord:
    """Get the next word to check in the authenticated user's lexicon.

    The next word is drawn using the lexicon's stored selection strategy, so
    the data stays consistent with how it was collected.
    """
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    if config["frequency_list"] is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lexicon `{lexicon_id}` has no frequency list configured.",
        )
    frequency_list = get_data().get_frequency_list(
        ListUsageConfig(**config["frequency_list"])
    )
    if frequency_list is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configured frequency list could not be loaded.",
        )
    answered: set[str] = postgres.get_answered_words(user_id, lexicon_id)
    try:
        word: str | None = select_next_word(
            frequency_list, answered, config["selection"]
        )
    except NotImplementedError as error:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(error)
        ) from error
    return NextWord(word=word)


@app.post(
    "/api/v1/me/lexicons/{lexicon_id}/answer",
    status_code=status.HTTP_204_NO_CONTENT,
)
def answer_lexicon_word(
    lexicon_id: str,
    request: AnswerRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> None:
    """Record an answer to a checked word in the user's lexicon."""
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    try:
        response: LexiconResponse = LexiconResponse(request.response)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid response `{request.response}`.",
        ) from error
    record: postgres.LexiconRecordRow = (
        request.word,
        response.to_code(),
        datetime.now(UTC),
        None,
    )
    postgres.save_lexicon(user_id, lexicon_id, config["language"], [record], [])


@app.get("/api/v1/me/lexicons/{lexicon_id}/translation")
async def get_lexicon_translation(
    lexicon_id: str,
    word: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> Translation:
    """Get a word's translation from the lexicon's configured dictionaries."""
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    dictionaries = get_data().get_dictionaries(
        [DictionaryUsageConfig(**d) for d in config["dictionaries"] or []]
    )
    elements: list[Element] | None = await dictionaries.to_text(
        word, Language.from_code(config["language"]), _DEFINITION_LANGUAGES
    )
    if not elements:
        return Translation(word=word, translation=None)
    return Translation(word=word, translation=elements_to_html(elements))


# Serve the static web interface from the same origin as the API, so the
# browser's `fetch` calls to `/api/v1/...` need no CORS configuration. Mounted
# last so it never shadows an API route.
_WEB_DIR: Path = Path(__file__).resolve().parents[2] / "web"
app.mount("/app", StaticFiles(directory=_WEB_DIR, html=True), name="web")
