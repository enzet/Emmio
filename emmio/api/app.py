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
from datetime import UTC, datetime, timedelta
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
from emmio.learn.config import LearnConfig
from emmio.learn.core import Learning, Response
from emmio.lexicon.config import LexiconConfig
from emmio.lexicon.core import Lexicon, LexiconResponse, select_next_word
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


class CourseSummary(BaseModel):
    """A learning course list row: identity plus computed short info."""

    course_id: str
    name: str
    learning_language: str
    words: int  # Distinct words studied.
    answers: int  # Total answers recorded.


class LexiconSummary(BaseModel):
    """A lexicon list row: identity plus computed short info."""

    lexicon_id: str
    language: str
    selection: str | None
    words: int  # Number of words checked so far.
    dont_last_week: int  # "Don't know" answers in the last 7 days.


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
) -> list[CourseSummary]:
    """List the authenticated user's learning courses."""
    return [
        CourseSummary(
            course_id=course_id,
            name=name,
            learning_language=language,
            words=words,
            answers=answers,
        )
        for course_id, name, language, words, answers in postgres.list_courses(
            user_id
        )
    ]


@app.get("/api/v1/me/lexicons")
def get_my_lexicons(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[LexiconSummary]:
    """List the authenticated user's lexicons."""
    return [
        LexiconSummary(
            lexicon_id=lexicon_id,
            language=language,
            selection=selection,
            words=words,
            dont_last_week=dont_last_week,
        )
        for lexicon_id, language, selection, words, dont_last_week in (
            postgres.list_lexicons(user_id)
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
    to_skip: bool = False  # Skip this word in future checks.


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


def _course_config_or_404(user_id: str, course_id: str) -> dict:
    """Get a course's reassembled config dict or raise 404."""

    config: dict | None = postgres.get_learn_config(user_id, course_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown course `{course_id}`.",
        )
    return config


async def _translate(
    word: str, language: str, dictionaries: list[dict] | None
) -> str | None:
    """Look a word up in the given dictionaries and render it as HTML."""

    collection = get_data().get_dictionaries(
        [DictionaryUsageConfig(**d) for d in dictionaries or []]
    )
    elements: list[Element] | None = await collection.to_text(
        word, Language.from_code(language), _DEFINITION_LANGUAGES
    )
    return elements_to_html(elements) if elements else None


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
        {"sk": True} if request.to_skip else None,
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
    html: str | None = await _translate(
        word, config["language"], config["dictionaries"]
    )
    return Translation(word=word, translation=html)


class LexiconStats(BaseModel):
    """Details and statistics for a single lexicon."""

    lexicon_id: str
    language: str
    selection: str | None
    precision_per_week: int  # Weekly "don't know" goal.
    words: int  # Distinct words checked.
    known: int  # Words whose last answer was "know".
    dont_know: int  # Words whose last answer was "don't know".
    precision: int  # Total "don't know" answers (the rate's precision).
    dont_last_week: int  # "Don't know" answers in the last 7 days.
    rate: float | None  # Vocabulary rate, or None if not enough data.


@app.get("/api/v1/me/lexicons/{lexicon_id}/stats")
def get_lexicon_stats(
    lexicon_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> LexiconStats:
    """Get details and statistics for one lexicon.

    Loads the lexicon's records to compute the vocabulary rate, so it is
    heavier than the list endpoint; intended for a single-lexicon view.
    """
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    # The path is vestigial (records live in the database); any value works.
    lexicon: Lexicon = Lexicon.from_config(
        Path(), lexicon_id, LexiconConfig(**config), user_id
    )
    now: datetime = datetime.now(UTC)
    known: int = sum(
        knowledge.knowing == LexiconResponse.KNOW
        for knowledge in lexicon.words.values()
    )
    dont_know: int = sum(
        knowledge.knowing == LexiconResponse.DONT
        for knowledge in lexicon.words.values()
    )
    return LexiconStats(
        lexicon_id=lexicon_id,
        language=config["language"],
        selection=config["selection"],
        precision_per_week=config["precision_per_week"],
        words=len(lexicon),
        known=known,
        dont_know=dont_know,
        precision=lexicon.count_unknowns(),
        dont_last_week=lexicon.count_unknowns(now - timedelta(days=7), now),
        rate=lexicon.get_last_rate(),
    )


# Learning. Only the spaced-repetition review of words already being learned is
# served; adding new words needs the interactive `Teacher` and is not yet here.


def _load_learning(user_id: str, course_id: str) -> Learning:
    """Load a user's course (records included) from the database."""

    config: dict = _course_config_or_404(user_id, course_id)
    # The path is vestigial (records live in the database); any value works.
    return Learning.from_config(
        Path(), LearnConfig(**config), course_id, user_id
    )


class CourseStats(BaseModel):
    """Details and statistics for a single learning course."""

    course_id: str
    name: str
    learning_language: str
    learning: int  # Words currently being learned.
    to_repeat: int  # Words due for repetition now.
    to_add: int  # New words still allowed today.
    added_today: int  # New words added today.
    answers: int  # Total answers recorded.
    actions: int  # Meaningful actions (right/wrong answers).


@app.get("/api/v1/me/courses/{course_id}/stats")
def get_course_stats(
    course_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> CourseStats:
    """Get details and statistics for one course.

    Loads the course's records to compute the repetition schedule, so it is
    heavier than the list endpoint; intended for a single-course view.
    """
    learning: Learning = _load_learning(user_id, course_id)
    return CourseStats(
        course_id=course_id,
        name=learning.config.name,
        learning_language=learning.learning_language.get_code(),
        learning=learning.count_questions_to_learn(),
        to_repeat=learning.count_questions_to_repeat(),
        to_add=learning.count_questions_to_add(),
        added_today=learning.count_questions_added_today(),
        answers=len(learning.get_records()),
        actions=learning.get_actions(),
    )


@app.get("/api/v1/me/courses/{course_id}/next")
def get_next_question(
    course_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> NextWord:
    """Get the next word due for repetition, or `None` if nothing is due."""
    learning: Learning = _load_learning(user_id, course_id)
    return NextWord(word=learning.get_next_question())


class CourseAnswerRequest(BaseModel):
    """A user's answer to a repetition question."""

    word: str
    response: str  # A `Response` value: "y" right, "n" wrong, "s" skip.


@app.post(
    "/api/v1/me/courses/{course_id}/answer",
    status_code=status.HTTP_204_NO_CONTENT,
)
def answer_question(
    course_id: str,
    request: CourseAnswerRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> None:
    """Record an answer to a repetition question."""
    config: dict = _course_config_or_404(user_id, course_id)
    try:
        response: Response = Response(request.response)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid response `{request.response}`.",
        ) from error
    record: postgres.LearnRecordRow = (
        request.word,
        response.value,
        datetime.now(UTC),
        None,
        None,
    )
    postgres.save_learning(
        user_id,
        course_id,
        config["name"],
        config["learning_language"],
        [record],
        [],
    )


@app.get("/api/v1/me/courses/{course_id}/translation")
async def get_course_translation(
    course_id: str,
    word: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> Translation:
    """Get a word's translation from the course's configured dictionaries."""
    config: dict = _course_config_or_404(user_id, course_id)
    html: str | None = await _translate(
        word, config["learning_language"], config.get("dictionaries")
    )
    return Translation(word=word, translation=html)


# Serve the static web interface from the same origin as the API, so the
# browser's `fetch` calls to `/api/v1/...` need no CORS configuration. Mounted
# last so it never shadows an API route.
_WEB_DIR: Path = Path(__file__).resolve().parents[2] / "web"
app.mount("/app", StaticFiles(directory=_WEB_DIR, html=True), name="web")
