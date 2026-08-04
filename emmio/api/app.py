"""Emmio HTTP API.

A thin FastAPI layer over the PostgreSQL storage in `emmio.postgres`.

Authentication: register with email and password, then log in to receive a
signed access token. Authenticated routes live under `/me` and derive the
current user from that token, so a client can only reach its own data. See
`emmio.api.auth` for the hashing and token details.

Run locally with:

    uvicorn emmio.api.app:app --reload
"""

import logging
import os
import random
import shutil
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import mkdtemp
from typing import Annotated, Any, Literal

import jwt
from fastapi import Depends, FastAPI, Form, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from emmio import postgres
from emmio.api import auth
from emmio.api.render import elements_to_html, to_html
from emmio.api.sessions import (
    LEARNING_REGISTRY,
    LEXICON_SESSIONS,
    LearningEntry,
    LexiconCheckSession,
)
from emmio.audio.config import AudioUsageConfig
from emmio.audio.transcode import to_browser_playable
from emmio.catalog import NON_PROPER_NOUNS
from emmio.data import Data
from emmio.dictionary.config import DictionaryUsageConfig
from emmio.dictionary.core import DictionaryCollection
from emmio.dictionary.en_wiktionary import kaikki_language_name
from emmio.language import KnownLanguages, Language, LanguageNotFoundError
from emmio.language_knowledge import (
    KNOWLEDGE_KINDS,
    KNOWLEDGE_KINDS_BY_CODE,
    KnowledgeKind,
    is_valid_caption,
    is_valid_knowledge_date,
    is_valid_knowledge_value,
)
from emmio.learn.config import LearningType
from emmio.learn.core import Learning, Response
from emmio.lexicon.config import LexiconConfig, LexiconSelection
from emmio.lexicon.core import (
    DEFAULT_N_STRATA,
    NOT_TO_CHECK_CATEGORY_CODES,
    NOT_TO_CHECK_TREE,
    RATE_ESTIMATOR_BY_SELECTION,
    AnswerType,
    CategoryNode,
    Lexicon,
    LexiconResponse,
    RateEstimator,
    estimate_rate_with_sd,
    select_next_word,
    stratum_of_rank,
)
from emmio.lexicon.curation import (
    EMMIO_CURATOR_NAME,
    EMMIO_CURATOR_USER_ID,
    classify_automatically,
)
from emmio.lexicon.goal import LexiconGoalState, compute_lexicon_goal_state
from emmio.lexicon.history import compute_rate_history, latest_windowed_rate
from emmio.lexicon.replay import replay
from emmio.lists.config import (
    ListUsageConfig,
    frequency_list_identifier,
    parse_frequency_list_identifier,
)
from emmio.lists.frequency_list import FrequencyList
from emmio.sentence.config import SentencesUsageConfig
from emmio.sentence.core import Sentence as ExampleSentence
from emmio.sentence.core import SentenceAndTranslations, SentenceElement
from emmio.ui import Element, Formatted, Text
from emmio.user.export import UnknownUserError, build_archive
from emmio.util import log_duration

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

logger: logging.Logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Surface Emmio's own logs (including `log_duration` timings).

    Uvicorn configures only its own `uvicorn*` loggers and leaves the root
    logger at `WARNING`, so `emmio.*` `INFO` records are otherwise dropped.
    Route them through Uvicorn's handler when present (matching its
    formatting), and fall back to a basic config when running outside Uvicorn.
    """
    emmio_logger: logging.Logger = logging.getLogger("emmio")
    emmio_logger.setLevel(logging.INFO)
    if emmio_logger.handlers:
        return
    uvicorn_handlers = logging.getLogger("uvicorn.error").handlers
    if uvicorn_handlers:
        for handler in uvicorn_handlers:
            emmio_logger.addHandler(handler)
        emmio_logger.propagate = False
    else:
        logging.basicConfig(level=logging.INFO)


_configure_logging()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Flush session working memory on shutdown.

    Answers are persisted per request, so only open session rows (start/end
    bookkeeping) are at stake here.
    """
    yield
    LEXICON_SESSIONS.flush()
    LEARNING_REGISTRY.flush()


app: FastAPI = FastAPI(title="Emmio API", version="0.1", lifespan=_lifespan)

# Tells clients (and `/docs`) where to obtain a token, and extracts the bearer
# token from the `Authorization` header on protected routes.
oauth2_scheme: OAuth2PasswordBearer = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login"
)


class User(BaseModel):
    """A user account."""

    user_id: str
    name: str


class LearningSummary(BaseModel):
    """A learning list row: identity plus computed short info."""

    learning_id: str
    name: str
    learning_language: str
    words: int  # Distinct words studied.
    answers: int  # Total answers recorded.
    learning_type: LearningType


class CourseSummary(BaseModel):
    """A course (language-level set of learnings) list row."""

    course_id: str
    name: str
    language: str
    learning_count: int


class CourseDetail(CourseSummary):
    """A single course's identity plus its learnings."""

    learnings: list[LearningSummary]


class CreatedCourse(BaseModel):
    """The identifier assigned to a freshly created course."""

    course_id: str


class LexiconSummary(BaseModel):
    """A lexicon list row: identity plus computed short info."""

    lexicon_id: str
    language: str
    selection: str | None
    name: str | None  # Display name; the identifier is used when not set.
    words: int  # Number of words checked so far.
    rate: float | None  # Vocabulary rate, or None if not enough data.
    sd: float | None  # Standard deviation of the rate estimate.
    is_main: bool  # Main lexicon for its language (its rate is language level).


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
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    remember: Annotated[bool, Form()] = False,  # noqa: FBT002
) -> Token:
    """Log in with email (as `username`) and password, returning a token.

    With `remember` set, the token lasts 7 days instead of the default hour.
    """
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
    ttl: timedelta = (
        auth.REMEMBER_TOKEN_TTL if remember else auth.ACCESS_TOKEN_TTL
    )
    return Token(access_token=auth.create_access_token(credentials[0], ttl))


class Profile(BaseModel):
    """The authenticated user's account details."""

    user_id: str
    name: str
    email: str | None


@app.get("/api/v1/me")
def get_me(user_id: Annotated[str, Depends(get_current_user)]) -> Profile:
    """Get the authenticated user's profile."""
    user: tuple[str, str, str | None] | None = postgres.get_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    return Profile(user_id=user[0], name=user[1], email=user[2])


class ChangePasswordRequest(BaseModel):
    """Payload to change the authenticated user's password."""

    current_password: str
    new_password: str = Field(min_length=8)


@app.post("/api/v1/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    request: ChangePasswordRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> None:
    """Change the authenticated user's password.

    Requires the current password, so a stolen access token alone cannot lock
    the owner out by changing it. The access token stays valid afterwards (a
    stateless JWT cannot be re-signed here); token revocation waits on the
    planned refresh-token work.
    """
    current_hash: str | None = postgres.get_password_hash(user_id)
    if current_hash is None or not auth.verify_password(
        request.current_password, current_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password is incorrect.",
        )
    postgres.set_password(user_id, auth.hash_password(request.new_password))


@app.delete("/api/v1/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(user_id: Annotated[str, Depends(get_current_user)]) -> None:
    """Delete the authenticated user and all their data.

    Irreversible: removes the account along with every lexicon, course,
    learning, and answer it owns. The caller's token becomes useless once the
    user is gone.
    """
    postgres.delete_user(user_id)
    LEXICON_SESSIONS.invalidate_user(user_id)
    LEARNING_REGISTRY.invalidate_user(user_id)


@app.get("/api/v1/me/export")
def export_me(
    user_id: Annotated[str, Depends(get_current_user)],
) -> FileResponse:
    """Download a ZIP archive of all data Emmio holds about the user.

    The data-portability export (GDPR Art. 15 / 20): account profile plus every
    learning, lexicon, and listening artifact as JSON. The archive is built in
    a temporary directory that is removed once the response has been sent.
    """
    temporary: Path = Path(mkdtemp())
    try:
        archive: Path = build_archive(
            user_id, _data_dir(), temporary / f"{user_id}-emmio-data.zip"
        )
    except UnknownUserError as error:
        shutil.rmtree(temporary, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=archive.name,
        background=BackgroundTask(shutil.rmtree, temporary, ignore_errors=True),
    )


@app.get("/api/v1/me/courses")
def get_my_courses(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[CourseSummary]:
    """List the authenticated user's courses (language-level sets)."""
    return [
        CourseSummary(
            course_id=course_id,
            name=name,
            language=language,
            learning_count=learning_count,
        )
        for (
            course_id,
            name,
            language,
            learning_count,
        ) in postgres.list_courses(user_id)
    ]


class CreateCourseRequest(BaseModel):
    """Payload to create a course: name and language."""

    name: str
    language: str


@app.post("/api/v1/me/courses", status_code=status.HTTP_201_CREATED)
def create_course(
    request: CreateCourseRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> CreatedCourse:
    """Create an empty course (a language-level set of learnings)."""
    try:
        language: Language = Language.from_code(request.language)
    except LanguageNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    course_id: str = _unique_artifact_id(
        request.language, {row[0] for row in postgres.list_courses(user_id)}
    )
    postgres.create_course(
        user_id, course_id, request.name, language.get_code()
    )
    return CreatedCourse(course_id=course_id)


@app.get("/api/v1/me/courses/{course_id}")
def get_course(
    course_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> CourseDetail:
    """Get a course's identity plus its learnings."""
    course: tuple[str, str] | None = postgres.get_course(user_id, course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown course `{course_id}`.",
        )
    name, language = course
    learnings: list[LearningSummary] = [
        LearningSummary(
            learning_id=learning_id,
            name=learning_name,
            learning_language=learning_language,
            words=words,
            answers=answers,
            learning_type=LearningType(learning_type),
        )
        for (
            learning_id,
            learning_name,
            learning_language,
            words,
            answers,
            learning_type,
        ) in postgres.list_learnings(user_id, course_id)
    ]
    return CourseDetail(
        course_id=course_id,
        name=name,
        language=language,
        learning_count=len(learnings),
        learnings=learnings,
    )


class UpdateCourseRequest(BaseModel):
    """Partial update to a course's settings; currently just its name."""

    name: str


@app.patch("/api/v1/me/courses/{course_id}")
def update_course(
    course_id: str,
    request: UpdateCourseRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> CourseSummary:
    """Rename a course. Its language is fixed at creation and never changes."""
    name: str = request.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course name cannot be empty.",
        )
    if not postgres.update_course_name(user_id, course_id, name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown course `{course_id}`.",
        )
    _, language = _course_or_404(user_id, course_id)
    return CourseSummary(
        course_id=course_id,
        name=name,
        language=language,
        learning_count=len(postgres.list_learnings(user_id, course_id)),
    )


@app.delete(
    "/api/v1/me/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_course(
    course_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> None:
    """Delete an empty course.

    Responds 404 when the user has no such course, and 409 when it still has
    learnings: delete those first.
    """
    try:
        deleted: bool = postgres.delete_course(user_id, course_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown course `{course_id}`.",
        )


_ROW_RATE_CACHE: dict[
    tuple[str, str], tuple[int | None, tuple[float, float] | None]
] = {}
"""Rate estimates by (user, lexicon), versioned by the user's newest record.

The bootstrapped estimators (logistic, threshold) cost a fraction of a
second per lexicon — too slow to recompute for every row on every table
load. A user's estimates only change when their answer history does, so the
newest lexicon record id (which an undo also moves) versions the cache, as
in the rate-graph `ETag`.
"""


def _row_rate_estimate(
    user_id: str,
    lexicon_id: str,
    selection: str | None,
    frequency_list_config: dict | None,
    get_sequence: Callable[[], list[int]],
    version: int | None = None,
    *,
    language: str,
) -> tuple[float, float] | None:
    """Estimate a list row's rate with the strategy-matched estimator.

    The quiet counterpart of `get_lexicon_rate_estimate` for the list
    endpoints, which show many lexicons at once: prerequisites the
    single-lexicon endpoint reports as HTTP errors (no estimator for the
    strategy, no frequency list) simply yield no rate here.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: the lexicon whose rate to estimate
    :param selection: the lexicon's stored selection strategy code
    :param frequency_list_config: the lexicon's frequency list usage
        configuration, required by the model-based estimators
    :param get_sequence: loads chronological responses (1 "know" / 0
        "don't"), needed only by the frequency estimator; called at most
        once, and not at all on a cache hit, since a lexicon's full answer
        log can run into the tens of thousands of rows
    :param version: the user's newest lexicon record id, keying
        `_ROW_RATE_CACHE`; None bypasses the cache
    :param language: the lexicon's language, needed to resolve a curated
        panel for `frequency_list_config` (see `_curated_pool_for_lexicon`)
    :return: (r̂, SD), or None if there is not enough data or the lexicon
        has no usable estimator
    """
    key: tuple[str, str] = (user_id, lexicon_id)
    if version is not None:
        hit = _ROW_RATE_CACHE.get(key)
        if hit is not None and hit[0] == version:
            return hit[1]
    estimate: tuple[float, float] | None = _compute_row_rate_estimate(
        user_id,
        lexicon_id,
        selection,
        frequency_list_config,
        get_sequence,
        language,
    )
    if version is not None:
        _ROW_RATE_CACHE[key] = (version, estimate)
    return estimate


_GOAL_STATE_CACHE: dict[
    tuple[str, str], tuple[tuple[int | None, date], LexiconGoalState]
] = {}
"""Goal states by (user, lexicon), versioned by newest record and today.

Mirrors `_ROW_RATE_CACHE`: `compute_lexicon_goal_state` reloads the full
per-lexicon record log and reruns the windowed estimator, costing as much as
the plain rate estimate it sits next to in the dashboard table but with no
cache of its own until now — the table's remaining slow part on a rate-cache
hit. Its trailing window's cutoff is `now - WINDOW_DAYS`, so unlike the plain
rate the result can drift as time alone passes (an old answer ages out of
the window with no new record); folding today's date into the version
accepts up to a day of that drift in exchange for not recomputing on every
table load.
"""


def _lexicon_goal_state(
    user_id: str,
    lexicon_id: str,
    selection: LexiconSelection,
    frequency_list: FrequencyList | None,
    now: datetime,
    version: int | None,
    *,
    n_strata: int = DEFAULT_N_STRATA,
    curated_words_by_stratum: dict[int, list[str]] | None = None,
) -> LexiconGoalState:
    """Get a lexicon's goal state, cached like `_row_rate_estimate`.

    :param version: the user's newest lexicon record id, as in
        `_row_rate_estimate`; None bypasses the cache
    :param n_strata: see `_curated_pool_for_lexicon`
    :param curated_words_by_stratum: see `_curated_pool_for_lexicon`
    """
    key: tuple[str, str] = (user_id, lexicon_id)
    cache_version: tuple[int | None, date] = (version, now.date())
    if version is not None:
        hit = _GOAL_STATE_CACHE.get(key)
        if hit is not None and hit[0] == cache_version:
            return hit[1]
    state: LexiconGoalState = compute_lexicon_goal_state(
        selection,
        frequency_list,
        postgres.get_lexicon_dated_record_log(user_id, lexicon_id),
        now,
        n_strata,
        curated_words_by_stratum,
    )
    if version is not None:
        _GOAL_STATE_CACHE[key] = (cache_version, state)
    return state


def _rate_and_sd(
    estimate: tuple[float, float] | None,
) -> tuple[float | None, float | None]:
    """Unpack an optional (rate, SD) estimate into nullable response fields."""
    return estimate if estimate is not None else (None, None)


def _frequency_list_or_none(
    frequency_list_config: dict | None,
) -> FrequencyList | None:
    """Load a frequency list usage config, or `None` if absent or unloadable."""
    if not frequency_list_config:
        return None
    return get_data().get_frequency_list(
        ListUsageConfig(**frequency_list_config)
    )


def _stratified_rate_windowed_or_full(
    user_id: str,
    lexicon_id: str,
    selection: LexiconSelection,
    frequency_list: FrequencyList,
    records: list[tuple[datetime, str, str]],
    n_strata: int = DEFAULT_N_STRATA,
    curated_words_by_stratum: dict[int, list[str]] | None = None,
) -> tuple[float, float] | None:
    """Estimate with the moving window, falling back to the full one.

    Mirrors the frequency estimator's own early-session fallback (its
    partial-log branch in `estimate_rate_frequency`): before the window first
    reaches the target SD, the full-history, latest-state-per-word estimate
    keeps a wider, less trustworthy number on screen instead of a blank
    field. `get_lexicon_selector_states` is fetched lazily since it is only
    needed for that fallback.

    :param n_strata: see `_curated_pool_for_lexicon`
    :param curated_words_by_stratum: see `_curated_pool_for_lexicon`
    """
    windowed: tuple[float, float] | None = latest_windowed_rate(
        selection,
        frequency_list,
        records,
        n_strata=n_strata,
        curated_words_by_stratum=curated_words_by_stratum,
    )
    if windowed is not None:
        return windowed
    states: dict[str, tuple[str | None, bool | None]] = (
        postgres.get_lexicon_selector_states(user_id, lexicon_id)
    )
    return estimate_rate_with_sd(
        selection,
        frequency_list,
        states,
        n_strata=n_strata,
        curated_words_by_stratum=curated_words_by_stratum,
    )


def _compute_row_rate_estimate(
    user_id: str,
    lexicon_id: str,
    selection: str | None,
    frequency_list_config: dict | None,
    get_sequence: Callable[[], list[int]],
    language: str,
) -> tuple[float, float] | None:
    """Estimate a list row's rate, uncached (see `_row_rate_estimate`)."""
    if selection is None:
        return None
    try:
        parsed: LexiconSelection = LexiconSelection(selection)
    except ValueError:
        return None
    method: RateEstimator | None = RATE_ESTIMATOR_BY_SELECTION.get(parsed)
    if method is None:
        return None
    if method == RateEstimator.FREQUENCY:
        return estimate_rate_with_sd(parsed, sequence=get_sequence())
    if not frequency_list_config:
        return None
    frequency_list: FrequencyList | None = get_data().get_frequency_list(
        ListUsageConfig(**frequency_list_config)
    )
    if frequency_list is None:
        return None
    curated: tuple[int, dict[int, list[str]]] | None = (
        _curated_pool_for_lexicon(
            {"language": language, "frequency_list": frequency_list_config}
        )
    )
    if method == RateEstimator.STRATIFIED:
        records: list[tuple[datetime, str, str]] = (
            postgres.get_lexicon_dated_record_log(user_id, lexicon_id)
        )
        return _stratified_rate_windowed_or_full(
            user_id,
            lexicon_id,
            parsed,
            frequency_list,
            records,
            curated[0] if curated else DEFAULT_N_STRATA,
            curated[1] if curated else None,
        )
    states: dict[str, tuple[str | None, bool | None]] = (
        postgres.get_lexicon_selector_states(user_id, lexicon_id)
    )
    return estimate_rate_with_sd(parsed, frequency_list, states)


@app.get("/api/v1/me/lexicons")
def get_my_lexicons(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[LexiconSummary]:
    """List the authenticated user's lexicons, sorted by vocabulary rate.

    The rate comes from the estimator matching each lexicon's selection
    strategy, as in the single-lexicon `rate-estimate` endpoint; lexicons
    without enough data (rate `None`) sort to the end. The answer sequence
    a cache-missing lexicon needs is loaded one lexicon at a time
    (`get_lexicon_answer_sequence`) rather than in the one bulk query this
    used to issue for every lexicon up front: a user's full answer history
    can run into the tens of thousands of rows, so on the common
    all-cache-hit load that bulk fetch cost more than the estimates it fed.
    """
    version: int | None = postgres.get_last_lexicon_record_id(user_id)
    summaries: list[LexiconSummary] = []
    for (
        lexicon_id,
        language,
        selection,
        words,
        is_main,
        name,
        frequency_list_config,
    ) in postgres.list_lexicons(user_id):
        estimate: tuple[float, float] | None = _row_rate_estimate(
            user_id,
            lexicon_id,
            selection,
            frequency_list_config,
            lambda lid=lexicon_id: postgres.get_lexicon_answer_sequence(
                user_id, lid
            ),
            version,
            language=language,
        )
        rate, sd = _rate_and_sd(estimate)
        summaries.append(
            LexiconSummary(
                lexicon_id=lexicon_id,
                language=language,
                selection=selection,
                name=name,
                words=words,
                rate=rate,
                sd=sd,
                is_main=is_main,
            )
        )
    summaries.sort(
        key=lambda s: s.rate if s.rate is not None else float("-inf"),
        reverse=True,
    )
    return summaries


class LexiconLanguage(BaseModel):
    """A language a lexicon can be created for (it has a frequency list)."""

    language: str  # ISO code, e.g. `uk`.


class LexiconStrategy(BaseModel):
    """A word-selection strategy offered when creating a lexicon."""

    value: LexiconSelection  # Stored on the lexicon, e.g. `frequency`.
    label: str  # Human-readable name shown in the UI.


# The single source of truth for the selectable strategies: the creation
# endpoint validates against it, `/lexicon-strategies` serves it, and the web
# UI populates its dropdowns from it. Every value here must be servable by
# `select_next_word` in `emmio.lexicon.core`.
LEXICON_STRATEGIES: tuple[LexiconStrategy, ...] = (
    LexiconStrategy(
        value=LexiconSelection.FREQUENCY, label="Frequency-weighted random"
    ),
    LexiconStrategy(value=LexiconSelection.RANDOM, label="Uniform random"),
    LexiconStrategy(value=LexiconSelection.TOP, label="Most frequent first"),
    LexiconStrategy(value=LexiconSelection.LOGISTIC, label="Logistic adaptive"),
    LexiconStrategy(
        value=LexiconSelection.THRESHOLD, label="Optimal threshold"
    ),
    LexiconStrategy(
        value=LexiconSelection.STRATIFIED,
        label="Stratified frequency-weighted random",
    ),
)
_VALID_SELECTIONS: frozenset[LexiconSelection] = frozenset(
    strategy.value for strategy in LEXICON_STRATEGIES
)


@app.get("/api/v1/lexicon-strategies", dependencies=[Depends(get_current_user)])
def get_lexicon_strategies() -> list[LexiconStrategy]:
    """List the word-selection strategies a new lexicon can be created with."""
    return list(LEXICON_STRATEGIES)


@app.get("/api/v1/lexicon-languages", dependencies=[Depends(get_current_user)])
def get_lexicon_languages() -> list[LexiconLanguage]:
    """List languages a new lexicon can be created for.

    A lexicon needs a frequency list to draw words from and Tatoeba sentences
    to show usage examples, so only languages with both are offered.
    """
    data = get_data()
    frequency_languages: set[str] = set(data.get_frequency_list_languages())
    sentence_languages: set[str] = data.get_sentence_languages()
    return [
        LexiconLanguage(language=language)
        for language in sorted(frequency_languages & sentence_languages)
    ]


class AlphabetLanguage(BaseModel):
    """A language a `LearningType.SYMBOL` (alphabet) learning can be for."""

    language: str  # ISO code, e.g. `uk`, or an ISO 15924 script code.


@app.get("/api/v1/alphabet-languages", dependencies=[Depends(get_current_user)])
def get_alphabet_languages() -> list[AlphabetLanguage]:
    """List languages an alphabet learning can be created for.

    An alphabet learning draws its items directly from `Language.symbols`, not
    from a frequency list or Tatoeba sentences, so it is offered for any
    language (or script, e.g. `deva` Devanagari) that knows its alphabet — a
    strictly larger set than `lexicon-languages`. Includes languages whose
    script also has its own generic entry (e.g. both `ka` Georgian and `geor`
    Georgian script): a course is fixed to one language, so its alphabet
    learning must be offered under that same code, not just under the script.
    """
    return [
        AlphabetLanguage(language=language.get_code())
        for language in KnownLanguages.get_languages()
        if language.has_symbols()
    ]


class TranslationLanguage(BaseModel):
    """A language a lexicon's words can be translated into."""

    language: str  # ISO code, e.g. `en`.


@app.get(
    "/api/v1/translation-languages", dependencies=[Depends(get_current_user)]
)
def get_translation_languages() -> list[TranslationLanguage]:
    """List languages a lexicon's words and sentences can be translated into.

    Google Translate covers any pair, so every language Emmio knows is offered
    as a translation target (English additionally gets richer Kaikki entries).
    """
    return [
        TranslationLanguage(language=language.get_code())
        for language in KnownLanguages.get_languages()
    ]


class FrequencyListOption(BaseModel):
    """A frequency list a lexicon or learning can draw new words from.

    A language may have more than one (e.g. several cached FrequencyWords
    years, or a custom configured list alongside them).
    """

    language: str  # ISO code, e.g. `fr`.
    id: str  # List config id, e.g. `frequency_words` or a custom list id.
    year: int | None = None  # FrequencyWords release year, when relevant.
    name: str  # Human-readable label for the picker.
    is_default: bool
    """Whether creation picks this option automatically when none is given."""

    curated: bool = False
    """Whether this draws only from a pre-reviewed curated panel.

    A curated option shares its `(id, year)` with the raw list it was built
    from (see `frequency_list_identifier`) — `curated` is what tells the two
    apart, since a language may offer both. Only `stratified` selection may
    be used with one (see `CuratedStratifiedSelector`).
    """


@app.get("/api/v1/frequency-lists", dependencies=[Depends(get_current_user)])
def get_frequency_lists() -> list[FrequencyListOption]:
    """List every frequency list available, across all languages."""
    data = get_data()
    defaults: dict[str, dict] = data.get_frequency_list_languages()
    options: list[FrequencyListOption] = [
        FrequencyListOption(
            language=option["language"],
            id=option["config"]["id"],
            year=option["config"].get("year"),
            name=option["name"],
            is_default=option["config"] == defaults.get(option["language"]),
        )
        for option in data.get_frequency_list_options()
    ]
    for (
        _list_id,
        language,
        frequency_list_id,
        name,
        _n_strata,
    ) in postgres.get_curated_lists():
        usage_config: ListUsageConfig = parse_frequency_list_identifier(
            frequency_list_id, language
        )
        options.append(
            FrequencyListOption(
                language=language,
                id=usage_config.id,
                year=usage_config.year,
                name=f"★ Curated: {name}",
                is_default=False,
                curated=True,
            )
        )
    return options


class FrequencyListSelection(BaseModel):
    """A specific frequency list to draw new words from, by id (and year)."""

    id: str
    year: int | None = None
    curated: bool = False
    """See `FrequencyListOption.curated`."""


class CreateLexiconRequest(BaseModel):
    """Payload to create a lexicon: the language and its translation targets."""

    language: str
    translation_languages: list[str] = Field(default_factory=lambda: ["en"])
    selection: str = "frequency"
    """Word-selection strategy; one of `LEXICON_STRATEGIES`."""
    frequency_list: FrequencyListSelection | None = None
    """Which frequency list to draw words from; defaults to the language's
    best available list when omitted."""


class CreatedLexicon(BaseModel):
    """The identifier assigned to a freshly created lexicon."""

    lexicon_id: str


def _is_known_language(code: str) -> bool:
    """Check whether `code` is a language Emmio knows."""
    try:
        Language.from_code(code)
    except LanguageNotFoundError:
        return False
    return True


def _validated_targets(codes: list[str]) -> list[str]:
    """Deduplicate translation targets, keeping only known languages.

    The shared validation of lexicon and learning creation and settings
    updates.

    :param codes: requested target language codes, in order
    :raises HTTPException: 400 when no valid target remains
    """
    targets: list[str] = [
        target for target in dict.fromkeys(codes) if _is_known_language(target)
    ]
    if not targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one valid translation language is required.",
        )
    return targets


def _validated_lexicon_or_400(
    user_id: str, lexicon_id: str, language: str
) -> None:
    """Check `lexicon_id` belongs to the user and matches `language`, or 400.

    Shared by learning creation and settings updates for both a learning's
    `check_lexicons` (skip already-known words) and `ask_lexicon` (ask about
    unseen ones first) references.
    """
    lexicon_config: dict | None = postgres.get_lexicon_config(
        user_id, lexicon_id
    )
    if lexicon_config is None or lexicon_config["language"] != language:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No lexicon `{lexicon_id}` for language `{language}`.",
        )


def _validated_question_types(question_types: list[str] | None) -> None:
    """Check every requested question type is one the learning teacher supports.

    :raises HTTPException: 400 listing the unsupported type(s)
    """
    if question_types is None:
        return
    unsupported: set[str] = set(question_types) - set(_ALL_QUESTION_TYPES)
    if unsupported:
        listed: str = ", ".join(sorted(unsupported))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported question type(s): {listed}.",
        )


def _frequency_list_or_400(data: Any, language: str) -> dict:
    """Get the language's frequency-list usage config, or raise 400.

    Both a lexicon and a learning draw their words from a frequency list, so
    creation is refused for languages without one.

    :param data: the shared `Data`; typed loosely because tests substitute a
        duck-typed stub for `get_data`
    """
    frequency_list: dict | None = data.get_frequency_list_languages().get(
        language
    )
    if frequency_list is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No frequency list available for language `{language}`.",
        )
    return frequency_list


def _validated_alphabet_language(language: str) -> Language:
    """Check `language` is known and has a defined alphabet, or raise 400.

    A `LearningType.SYMBOL` learning draws its items from `Language.symbols`
    instead of a frequency list, so it needs the alphabet defined instead.
    """
    try:
        known: Language | None = Language.from_code(language)
    except LanguageNotFoundError:
        known = None
    if known is None or not known.has_symbols():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No alphabet available for language `{language}`.",
        )
    return known


def _chosen_frequency_list_or_400(
    data: Any, language: str, choice: FrequencyListSelection | None
) -> dict:
    """Resolve the frequency list to draw new words from.

    Defaults to the language's best available list (`_frequency_list_or_400`)
    when `choice` is omitted; otherwise validates the requested (id, year)
    against `get_frequency_list_options` so a learning can't be pointed at a
    list that doesn't exist or belongs to another language. `choice.curated`
    additionally requires a curated panel to exist for that exact list (see
    `FrequencyListOption.curated`); the returned config carries the flag
    through so the caller (only `create_lexicon` acts on it) knows to store
    it.

    :param data: the shared `Data`; typed loosely because tests substitute a
        duck-typed stub for `get_data`
    """
    if choice is None:
        return _frequency_list_or_400(data, language)
    for option in data.get_frequency_list_options():
        if (
            option["language"] == language
            and option["config"]["id"] == choice.id
            and option["config"].get("year") == choice.year
        ):
            if not choice.curated:
                return option["config"]
            frequency_list_id: str = frequency_list_identifier(
                ListUsageConfig(
                    id=option["config"]["id"],
                    language=language,
                    year=option["config"].get("year"),
                )
            )
            if postgres.get_curated_list_id(language, frequency_list_id):
                return {**option["config"], "curated": True}
            break
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(f"No frequency list `{choice.id}` for language `{language}`."),
    )


def _unique_artifact_id(language: str, existing: set[str]) -> str:
    """Derive an unused identifier from the language code: `fr`, `fr_2`, ..."""
    artifact_id: str = language
    suffix: int = 2
    while artifact_id in existing:
        artifact_id = f"{language}_{suffix}"
        suffix += 1
    return artifact_id


# Languages whose alphabet is authored under a shared script's dictionary
# (e.g. `geor_alphabet.json`, keyed by the ISO 15924 script code) rather than
# their own — see `KnownLanguages`'s "Script identities" section.
_ALPHABET_SCRIPT_FOR_LANGUAGE: dict[str, str] = {
    "hy": "armn",
    "ka": "geor",
    "ko": "hang",
    "hi": "deva",
    "ar": "arab",
    "bg": "cyrl",
    "kk": "cyrl",
    "mk": "cyrl",
    "sr": "cyrl",
}


def _alphabet_dictionary_config(data: Any, language: str) -> dict | None:
    """Build a symbol learning's `dictionaries` entry for its letter names.

    Letter-name data (name, transcription, per-language definitions) is
    hand-authored per script as a `structured` dictionary, id
    `<code>_alphabet` (see `dictionaries/config.json`). Most languages have
    none yet, in which case a symbol learning simply has no translations.
    """
    code: str = _ALPHABET_SCRIPT_FOR_LANGUAGE.get(language, language)
    dictionary_id: str = f"{code}_alphabet"
    if dictionary_id in data.dictionaries.dictionaries:
        return {"id": dictionary_id}
    return None


def _with_kaikki(data: Any, targets: list[str], language: str) -> bool:
    """Whether to configure the Kaikki (en.wiktionary) dictionary.

    English must be a target and kaikki.org must cover the language; the
    dictionary itself is downloaded in the background on first use.

    :param data: the shared `Data`; typed loosely because tests substitute a
        duck-typed stub for `get_data`
    """
    return "en" in targets and data.dictionaries.can_download_kaikki(
        Language.from_code(language)
    )


def _translation_config(
    language: str, targets: list[str], *, with_kaikki: bool
) -> tuple[list[dict], list[dict]]:
    """Build a lexicon's `dictionaries` and `sentences` config.

    Dictionaries: a Kaikki (en.wiktionary) entry when `with_kaikki` is set
    (English is a target and kaikki.org has the language; it is downloaded in
    the background on first use), plus a Google Translate entry into every
    target language. Sentences: Tatoeba examples in the lexicon's language,
    translated into the target languages.

    :param language: the lexicon's language code
    :param targets: language codes to translate words and sentences into
    :param with_kaikki: whether to add the Kaikki English-definition dictionary
    """
    dictionaries: list[dict] = []
    if with_kaikki:
        dictionaries.append(
            {
                "id": "kaikki",
                "from_language": language,
                "name": kaikki_language_name(Language.from_code(language)),
            }
        )
    dictionaries.extend(
        {
            "id": "google_translate",
            "from_language": language,
            "to_language": target,
        }
        for target in targets
    )
    sentences: list[dict] = [
        {
            "id": "tatoeba",
            "language": language,
            "translation_languages": targets,
        }
    ]
    return dictionaries, sentences


@app.post("/api/v1/me/lexicons", status_code=status.HTTP_201_CREATED)
def create_lexicon(
    request: CreateLexiconRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> CreatedLexicon:
    """Create a lexicon for a language.

    The lexicon samples words by the requested strategy from the language's
    frequency list (the language's best available one, or a specific one
    when `frequency_list` is given), shows usage examples from Tatoeba, and
    translates words into the requested target languages. Its id is the
    language code, suffixed if one already exists. If the language has no
    main lexicon yet, the new one is set as main so it shows up on the home
    page at once; an existing main lexicon keeps its status.
    """
    if request.selection not in _VALID_SELECTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported selection strategy `{request.selection}`. "
                f"Choose one of: {', '.join(sorted(_VALID_SELECTIONS))}."
            ),
        )
    selection: LexiconSelection = LexiconSelection(request.selection)
    if (
        request.frequency_list is not None
        and request.frequency_list.curated
        and selection != LexiconSelection.STRATIFIED
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A curated list only supports the `stratified` selection "
                "strategy: it is a small, fixed, pre-reviewed panel, not a "
                "rankable full list for the other strategies to work with."
            ),
        )

    data = get_data()
    frequency_list: dict = _chosen_frequency_list_or_400(
        data, request.language, request.frequency_list
    )
    targets: list[str] = _validated_targets(request.translation_languages)
    lexicon_id: str = _unique_artifact_id(
        request.language, {row[0] for row in postgres.list_lexicons(user_id)}
    )
    with_kaikki: bool = _with_kaikki(data, targets, request.language)
    dictionaries, sentences = _translation_config(
        request.language, targets, with_kaikki=with_kaikki
    )
    config: dict = {
        "language": request.language,
        "selection": selection.value,
        "frequency_list": frequency_list,
        "dictionaries": dictionaries,
        "sentences": sentences,
    }
    postgres.store_lexicon_config(user_id, lexicon_id, config)
    if not postgres.has_main_lexicon(user_id, request.language):
        postgres.set_main_lexicon(user_id, lexicon_id)
    return CreatedLexicon(lexicon_id=lexicon_id)


@app.delete(
    "/api/v1/me/lexicons/{lexicon_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_lexicon(
    lexicon_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> None:
    """Delete a lexicon and all its answer history.

    Irreversible: removes the lexicon along with every word and record it owns.
    Responds 404 when the user has no such lexicon.
    """
    if not postgres.delete_lexicon(user_id, lexicon_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown lexicon `{lexicon_id}`.",
        )
    LEXICON_SESSIONS.invalidate(user_id, lexicon_id)


LEXICON_ID_PATTERN: str = r"^[a-z0-9][a-z0-9_-]{0,63}$"
"""Shape of a lexicon identifier; it appears in URLs, so keep it a slug."""


class LexiconSettings(BaseModel):
    """A lexicon's editable settings.

    `language` and `selection` are identity, immutable for the lexicon's life;
    they are included read-only so the form can display them.
    """

    lexicon_id: str
    language: str
    selection: str
    name: str | None  # Display name; the identifier is used when not set.
    translation_languages: list[str]
    frequency_list_name: str | None
    """Human-readable name of the frequency list words are drawn from.

    `None` for a lexicon with no frequency list (e.g. an alphabet lexicon).
    """


class UpdateLexiconRequest(BaseModel):
    """Partial update to a lexicon's settings; omitted fields are unchanged."""

    lexicon_id: str | None = Field(default=None, pattern=LEXICON_ID_PATTERN)
    name: str | None = None  # An empty (or blank) name clears it.
    translation_languages: list[str] | None = None


def _lexicon_translation_languages(config: dict) -> list[str]:
    """Derive a lexicon's translation targets from its stored config.

    Unlike a learning (`base_languages`), a lexicon does not store its targets
    directly; they only exist inside the dictionary and sentence config they
    generated, so they are read back from the Google Translate entries and the
    Tatoeba `translation_languages`. A lexicon created before targets were
    auto-configured yields an empty list — saving targets in the settings form
    backfills its config.
    """
    targets: dict[str, None] = {}  # An ordered set.
    for dictionary in config.get("dictionaries") or []:
        if dictionary.get("id") == "google_translate" and (
            target := dictionary.get("to_language")
        ):
            targets[target] = None
    for sentences in config.get("sentences") or []:
        for target in sentences.get("translation_languages") or []:
            targets[target] = None
    return list(targets)


def _frequency_list_name(
    data: Any, frequency_list_config: dict | None
) -> str | None:
    """Look up a human-readable name for a stored frequency-list usage config.

    Matches the stored config against `get_frequency_list_options`, falling
    back to the raw list id if no option matches exactly (e.g. a list that
    used to be configured but has since been removed).
    """
    if not frequency_list_config:
        return None
    for option in data.get_frequency_list_options():
        if option["config"] == frequency_list_config:
            return option["name"]
    return frequency_list_config.get("id")


def _lexicon_settings(lexicon_id: str, config: dict) -> LexiconSettings:
    """Read a lexicon's editable settings out of its flat config."""
    return LexiconSettings(
        lexicon_id=lexicon_id,
        language=config["language"],
        selection=config["selection"],
        name=config.get("name"),
        translation_languages=_lexicon_translation_languages(config),
        frequency_list_name=_frequency_list_name(
            get_data(), config.get("frequency_list")
        ),
    )


@app.get("/api/v1/me/lexicons/{lexicon_id}/settings")
def get_lexicon_settings(
    lexicon_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> LexiconSettings:
    """Get a lexicon's editable settings (to pre-fill an edit form)."""
    return _lexicon_settings(
        lexicon_id, _lexicon_config_or_404(user_id, lexicon_id)
    )


@app.patch("/api/v1/me/lexicons/{lexicon_id}/settings")
def update_lexicon_settings(
    lexicon_id: str,
    request: UpdateLexiconRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> LexiconSettings:
    """Update a lexicon's settings; omitted fields keep their current value.

    Changing the translation languages regenerates the derived translation
    config (dictionaries, sentences) from the same builders lexicon creation
    uses — which is also how a lexicon created before targets were
    auto-configured gets them backfilled. The lexicon's identity (language,
    selection, frequency list) stays untouched, so the rate estimate and the
    answer history keep their meaning.

    Renaming the identifier (`lexicon_id`) moves the lexicon and all its
    history to the new id (words and records follow automatically); the old
    id — and any URL containing it — stops working. Responds 409 when the new
    id is already taken.
    """
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)

    if request.name is not None:
        if name := request.name.strip():
            config["name"] = name
        else:
            config.pop("name", None)

    if request.translation_languages is not None:
        targets: list[str] = _validated_targets(request.translation_languages)
        language: str = config["language"]
        dictionaries, sentences = _translation_config(
            language,
            targets,
            with_kaikki=_with_kaikki(get_data(), targets, language),
        )
        config["dictionaries"] = dictionaries
        config["sentences"] = sentences

    new_id: str = lexicon_id
    if request.lexicon_id is not None and request.lexicon_id != lexicon_id:
        try:
            postgres.rename_lexicon(user_id, lexicon_id, request.lexicon_id)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Lexicon `{request.lexicon_id}` already exists.",
            ) from error
        LEXICON_SESSIONS.invalidate(user_id, lexicon_id)
        new_id = request.lexicon_id

    postgres.store_lexicon_config(user_id, new_id, config)
    # The open session (if any) was built on the old settings.
    LEXICON_SESSIONS.invalidate(user_id, new_id)
    return _lexicon_settings(new_id, config)


class CreateLearningRequest(BaseModel):
    """Payload to add a learning to a course."""

    learning_type: LearningType = LearningType.WORD
    """What kind of item this learning drills; immutable after creation."""
    translation_languages: list[str] = Field(default_factory=lambda: ["en"])
    name: str | None = None
    """Display name; defaults to the language's own name when omitted."""
    max_for_day: int = Field(default=10, ge=0)
    """Maximum number of new words introduced per day."""
    play_audio: bool = True
    """Whether to play pronunciation audio during a session."""
    question_types: list[str] | None = None
    """Which question types this learning may use; all when omitted."""
    lexicon_id: str | None = None
    """An existing lexicon for the same language whose already-known words are
    skipped when the learning picks new questions."""
    ask_lexicon_id: str | None = None
    """An existing lexicon for the same language: an unseen new word is shown
    as a know/don't-know check first, recorded there, before being taught."""
    frequency_list: FrequencyListSelection | None = None
    """Which frequency list to draw new words from (`learning_type=word`
    only); defaults to the language's best available list when omitted."""


class CreatedLearning(BaseModel):
    """The identifier assigned to a freshly created learning."""

    learning_id: str


def _course_or_404(user_id: str, course_id: str) -> tuple[str, str]:
    """Get a course's (name, language) or raise 404."""
    course: tuple[str, str] | None = postgres.get_course(user_id, course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown course `{course_id}`.",
        )
    return course


@app.post(
    "/api/v1/me/courses/{course_id}/learnings",
    status_code=status.HTTP_201_CREATED,
)
def create_learning(
    course_id: str,
    request: CreateLearningRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> CreatedLearning:
    """Add a learning to an existing course, in the course's language.

    A `word` learning (the default) draws new words from the language's
    frequency list (skipping ones a dictionary marks uncommon), shows Tatoeba
    usage examples, and translates into the requested target languages;
    `frequency_list` picks among a language's several available lists (e.g.
    cached FrequencyWords years), defaulting to the best one when omitted. A
    `symbol` learning instead drills the language's own alphabet
    (`Language.symbols`) directly and has no frequency list or sentences; it
    gets a translation dictionary only if a hand-authored one exists for its
    script (see `_alphabet_dictionary_config`). Its id is the language code,
    suffixed if one already exists. When `lexicon_id` names one of the user's
    own lexicons for the same language, words already known there are
    skipped; `ask_lexicon_id` instead asks about an unseen word there first,
    before teaching it.
    """
    _, language = _course_or_404(user_id, course_id)
    data = get_data()
    targets: list[str] = _validated_targets(request.translation_languages)
    if request.lexicon_id is not None:
        _validated_lexicon_or_400(user_id, request.lexicon_id, language)
    if request.ask_lexicon_id is not None:
        _validated_lexicon_or_400(user_id, request.ask_lexicon_id, language)
    _validated_question_types(request.question_types)
    learning_id: str = _unique_artifact_id(
        language, {row[0] for row in postgres.list_learnings(user_id)}
    )

    new_question: dict = {}
    dictionaries: list[dict] = []
    sentences: list[dict] = []
    if request.learning_type == LearningType.SYMBOL:
        alphabet_language: Language = _validated_alphabet_language(language)
        default_name: str = f"{alphabet_language.get_name()} alphabet"
        alphabet_dictionary: dict | None = _alphabet_dictionary_config(
            data, language
        )
        if alphabet_dictionary is not None:
            dictionaries = [alphabet_dictionary]
    else:
        frequency_list: dict = _chosen_frequency_list_or_400(
            data, language, request.frequency_list
        )
        with_kaikki: bool = _with_kaikki(data, targets, language)
        dictionaries, sentences = _translation_config(
            language, targets, with_kaikki=with_kaikki
        )
        # New words come from the frequency list; when a Kaikki dictionary is
        # available it also filters out words it marks uncommon (mere word
        # forms).
        new_question["pick_from"] = [frequency_list]
        if with_kaikki:
            new_question["ignore_not_common"] = [
                {
                    "id": "kaikki",
                    "from_language": language,
                    "name": kaikki_language_name(Language.from_code(language)),
                }
            ]
        default_name = Language.from_code(language).get_name()

    if request.lexicon_id is not None:
        new_question["check_lexicons"] = [{"id": request.lexicon_id}]
    if request.ask_lexicon_id is not None:
        new_question["ask_lexicon"] = {"id": request.ask_lexicon_id}
    scheme: dict = {"new_question": new_question}
    if request.question_types:
        scheme["question_types"] = request.question_types
    name: str = (
        request.name.strip() if request.name and request.name.strip() else ""
    ) or default_name
    config: dict = {
        "name": name,
        "course_id": course_id,
        "learning_type": request.learning_type.value,
        "learning_language": language,
        "base_languages": targets,
        "scheme": scheme,
        "dictionaries": dictionaries,
        "sentences": sentences,
        "audio": data.get_audio_config(language),
        "max_for_day": request.max_for_day,
        "play_audio": request.play_audio,
    }
    postgres.store_learning_config(user_id, learning_id, config)
    return CreatedLearning(learning_id=learning_id)


@app.delete(
    "/api/v1/me/learnings/{learning_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_learning(
    learning_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> None:
    """Delete a learning and all its answer history.

    Irreversible: removes the learning along with every record and session it
    owns. Responds 404 when the user has no such learning.
    """
    if not postgres.delete_learning(user_id, learning_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown learning `{learning_id}`.",
        )
    LEARNING_REGISTRY.invalidate(user_id, learning_id)


class LearningSettings(BaseModel):
    """A learning's editable settings."""

    name: str
    learning_type: LearningType  # Read-only: fixed at creation.
    learning_language: str
    translation_languages: list[str]  # `base_languages`.
    max_for_day: int  # New words introduced per day.
    play_audio: bool  # Whether to play pronunciation audio in a session.
    question_types: list[str]  # Allowed question types; all four when unset.
    lexicon_id: str | None  # Skips words already known there, if set.
    ask_lexicon_id: str | None  # Asks about unseen words there first, if set.
    extra_symbols: str  # Letters a basic keyboard may lack, for tap buttons.


class UpdateLearningRequest(BaseModel):
    """Partial update to a learning's settings; omitted fields are unchanged."""

    name: str | None = None
    translation_languages: list[str] | None = None
    max_for_day: int | None = Field(default=None, ge=0)
    play_audio: bool | None = None
    question_types: list[str] | None = None
    """Omitted keeps the current value; an empty list allows all types."""
    lexicon_id: str | None = None
    """Omitted keeps the current value; an empty string clears it."""
    ask_lexicon_id: str | None = None
    """Omitted keeps the current value; an empty string clears it."""


def _learning_settings(config: dict) -> LearningSettings:
    """Read a learning's editable settings out of its flat config."""
    try:
        extra_symbols: str = Language.from_code(
            config["learning_language"]
        ).get_extra_symbols()
    except LanguageNotFoundError:
        extra_symbols = ""
    new_question: dict = (config.get("scheme") or {}).get("new_question") or {}
    check_lexicons: list[dict] = new_question.get("check_lexicons") or []
    ask_lexicon: dict | None = new_question.get("ask_lexicon")
    return LearningSettings(
        name=config["name"],
        learning_type=config.get("learning_type", LearningType.WORD),
        learning_language=config["learning_language"],
        translation_languages=config.get("base_languages") or [],
        max_for_day=config.get("max_for_day", 10),
        play_audio=config.get("play_audio", True),
        question_types=(config.get("scheme") or {}).get("question_types")
        or list(_ALL_QUESTION_TYPES),
        lexicon_id=check_lexicons[0]["id"] if check_lexicons else None,
        ask_lexicon_id=ask_lexicon["id"] if ask_lexicon else None,
        extra_symbols=extra_symbols,
    )


@app.get("/api/v1/me/learnings/{learning_id}/settings")
def get_learning_settings(
    learning_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> LearningSettings:
    """Get a learning's editable settings (to pre-fill an edit form)."""
    return _learning_settings(_learning_config_or_404(user_id, learning_id))


@app.patch("/api/v1/me/learnings/{learning_id}/settings")
def update_learning_settings(
    learning_id: str,
    request: UpdateLearningRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> LearningSettings:
    """Update a learning's settings; omitted fields keep their current value.

    Changing the translation languages regenerates the derived translation and
    audio config (dictionaries, sentences, audio) from the same builders
    learning creation uses. The learning's `learning_language` is immutable
    and its answer history is untouched (records carry their own provenance).
    """
    config: dict = _learning_config_or_404(user_id, learning_id)
    data = get_data()
    language: str = config["learning_language"]

    if request.name is not None:
        name: str = request.name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Learning name cannot be empty.",
            )
        config["name"] = name

    if request.max_for_day is not None:
        config["max_for_day"] = request.max_for_day

    if request.play_audio is not None:
        config["play_audio"] = request.play_audio

    if request.translation_languages is not None:
        targets: list[str] = _validated_targets(request.translation_languages)
        dictionaries, sentences = _translation_config(
            language, targets, with_kaikki=_with_kaikki(data, targets, language)
        )
        config["base_languages"] = targets
        config["dictionaries"] = dictionaries
        config["sentences"] = sentences
        config["audio"] = data.get_audio_config(language)

    if (
        request.question_types is not None
        or request.lexicon_id is not None
        or request.ask_lexicon_id is not None
    ):
        scheme: dict = config.setdefault("scheme", {})
        new_question: dict = scheme.setdefault("new_question", {})

        if request.question_types is not None:
            if request.question_types:
                _validated_question_types(request.question_types)
                scheme["question_types"] = request.question_types
            else:
                scheme.pop("question_types", None)

        if request.lexicon_id is not None:
            if request.lexicon_id:
                _validated_lexicon_or_400(user_id, request.lexicon_id, language)
                new_question["check_lexicons"] = [{"id": request.lexicon_id}]
            else:
                new_question.pop("check_lexicons", None)

        if request.ask_lexicon_id is not None:
            if request.ask_lexicon_id:
                _validated_lexicon_or_400(
                    user_id, request.ask_lexicon_id, language
                )
                new_question["ask_lexicon"] = {"id": request.ask_lexicon_id}
            else:
                new_question.pop("ask_lexicon", None)

    postgres.store_learning_config(user_id, learning_id, config)
    # The cached instance (if any) was built on the old settings.
    LEARNING_REGISTRY.invalidate(user_id, learning_id)
    return _learning_settings(config)


class NextWord(BaseModel):
    """The next word to check, or `None` when the list is exhausted."""

    word: str | None


class StratumAnswer(BaseModel):
    """One know/don't-know answer placed in its frequency stratum."""

    stratum: int
    """0-based log-uniform stratum index of the answered word's rank."""

    know: bool
    """True for a "know" answer, False for "don't know"."""


class WordCard(BaseModel):
    """One upcoming word with its last-answer context (if any)."""

    word: str
    last_response: str | None  # Human label of the last answer, e.g. "know".
    last_time: datetime | None  # When the word was last answered.
    accepted: list[str] | None = None
    """Typed answers that count as correct, for live "auto-accept on match".

    Set for learning cards (the user types the word); `None` for lexicon cards
    (a yes/no check, nothing is typed). The client compares the typed text
    against this set and accepts on a hit, so the language-matching rule stays a
    server concern rather than being reimplemented in the client.
    """

    rank: int | None = None
    """1-based position in the lexicon's frequency list (check page status).

    Set for lexicon cards whose word is in the frequency list; `None` for
    learning cards.
    """

    stratum: int | None = None
    """0-based log-uniform stratum index of the word's rank (SFWR only)."""


# Sentences containing a word to inspect when one example is enough. Keeping
# this small avoids processing the hundreds a common word may appear in.
_SENTENCE_SAMPLE: int = 30


class NextWords(BaseModel):
    """A batch of upcoming words, soonest first; empty when exhausted.

    Lets the client prefetch a queue instead of fetching one word per answer.
    """

    language: str  # ISO code of the words' language, e.g. `fr`.
    words: list[WordCard]
    selection: LexiconSelection | None = None
    """The lexicon's selection strategy (lexicon checks only)."""
    list_size: int | None = None
    """Number of words in the lexicon's frequency list (lexicon checks only)."""
    strata: int | None = None
    """Total number of strata, when `selection` is `stratified`."""

    propagated: list[StratumAnswer] = []
    """Know/don't-know answers auto-recorded (never presented) while drawing
    this batch — a stale or skip-flagged word propagated from this or a
    sibling lexicon (see `_skip_decision`). They are real records and do
    count toward the rate estimate the moment they land, but a client
    driving a live chart from `/answer` alone would otherwise never see
    them: nothing else in this response calls them out. Empty outside
    `stratified` (no stratum to place them in) or a non-word propagation
    (no "know" boolean to plot)."""


# Short human labels for stored response codes, for the "last answer" hint.
_LEXICON_RESPONSE_LABELS: dict[str, str] = {
    LexiconResponse.KNOW.to_code(): "know",
    LexiconResponse.KNOW_SEMANTIC_CLASS.to_code(): "know class",
    LexiconResponse.DONT.to_code(): "don't know",
    LexiconResponse.DONT_BUT_PROPER_NOUN_TOO.to_code(): "proper noun",
    LexiconResponse.NOT_A_WORD.to_code(): "not a word",
}
_LEARN_RESPONSE_LABELS: dict[str, str] = {
    Response.RIGHT.value: "right",
    Response.WRONG.value: "wrong",
    Response.SKIP.value: "skip",
}


def _accepted_forms(word: str, language: Language) -> list[str]:
    """Get the word plus its simplified spellings, e.g. Esperanto "anstataux".

    Typing any of these counts as producing the word, mirroring the terminal
    teacher's `decode_text` on typed answers.
    """
    return [word, *language.encode_texts(word)]


def _word_cards(
    words: list[str],
    answers: dict[str, tuple[str, datetime]],
    labels: dict[str, str],
    *,
    typed_language: Language | None = None,
) -> list[WordCard]:
    """Build word cards, attaching each word's last answer.

    :param typed_language: set when the card is answered by typing the word
        (learning), in which case `accepted` is populated so the client can
        auto-accept a correct entry, including the language's simplified
        spellings; lexicon cards leave it `None`.
    """
    cards: list[WordCard] = []
    for word in words:
        code_time: tuple[str, datetime] | None = answers.get(word)
        cards.append(
            WordCard(
                word=word,
                last_response=(
                    labels.get(code_time[0], code_time[0])
                    if code_time
                    else None
                ),
                last_time=code_time[1] if code_time else None,
                accepted=(
                    _accepted_forms(word, typed_language)
                    if typed_language
                    else None
                ),
            )
        )
    return cards


def _example_sentences(
    word: str, language: str, configs: list[dict] | None
) -> list:
    """Look up a handful of example sentences containing a word.

    Inspects a small sample rather than all (hundreds) of a common word's
    sentences, since only one example is ever shown.
    """
    if not configs:
        return []
    with log_duration(f"sentence lookup for `{word}` ({language})", logger):
        return (
            get_data()
            .get_sentences_data()
            .get(
                word,
                [SentencesUsageConfig(**config) for config in configs],
                max_number=_SENTENCE_SAMPLE,
            )
        )


def _render_sentence(
    sentence: ExampleSentence, language: Language, word: str, *, mask: bool
) -> str:
    """Render a sentence to HTML, with the target word bold or blanked.

    :param mask: replace the word with underscores (a recall prompt) instead of
        bolding it
    """
    text: Text = Text()
    for part, element in sentence.get_words(language):
        if element == SentenceElement.WORD and language.normalize(part) == word:
            text.add("_" * len(part) if mask else Formatted(part, "bold"))
        else:
            text.add(part)
    return to_html(text)


def _sentence_html(
    word: str, language: str, configs: list[dict] | None
) -> str | None:
    """Render one example sentence for a word, with the word bolded.

    The CLI's usage example: a sentence in the word's language with the target
    word highlighted (its translation is intentionally not shown). Returns
    `None` if there are no sentence sources or none are found.
    """
    examples: list[SentenceAndTranslations] = _example_sentences(
        word, language, configs
    )
    if not examples:
        return None
    return _render_sentence(
        random.choice(examples).sentence,
        Language.from_code(language),
        word,
        mask=False,
    )


def _learning_sentence(
    word: str,
    language: str,
    configs: list[dict] | None,
    base_languages: list[str],
) -> tuple[int, str, str] | None:
    """One example sentence (word blanked) plus one of its translations.

    Only sentences that have a translation into one of the learning's base
    languages are used, so a learner always sees a translated example. Returns
    `(sentence_id, sentence_html, translation_text)`, or `None` when no such
    sentence exists. The id is recorded as provenance with the answer.
    """
    examples: list[SentenceAndTranslations] = _example_sentences(
        word, language, configs
    )
    if not examples:
        return None
    bases: list[Language] = [
        Language.from_code(code) for code in base_languages
    ]
    # Keep only examples that carry a translation into a base language, pairing
    # each with that language's translations to draw one from.
    candidates: list[tuple[SentenceAndTranslations, list[ExampleSentence]]] = []
    for example in examples:
        for base in bases:
            translations = example.translations.get(base)
            if translations:
                candidates.append((example, translations))
                break
    if not candidates:
        return None
    example, translations = random.choice(candidates)
    sentence_html: str = _render_sentence(
        example.sentence, Language.from_code(language), word, mask=True
    )
    return (
        example.sentence.id_,
        sentence_html,
        random.choice(translations).text,
    )


async def _short_translation(
    word: str,
    language: Language,
    dictionaries: DictionaryCollection,
    base_languages: list[Language],
) -> str | None:
    """Get a single-word translation of a word, for multiple-choice options.

    Uses the dictionary's one-word definitions (the same source the listen
    module's quiz uses), trying base languages in order. Returns `None` when no
    short translation exists — such words simply can't be asked as choice or
    connect questions.
    """
    items = await dictionaries.get_items(word, language)
    for base_language in base_languages:
        for item in items:
            definitions: list[str] = item.get_one_word_definitions(
                base_language
            )
            if definitions:
                return definitions[0]
    return None


# Most words a single `/next` request may prefetch.
_BATCH_MAX: int = 50

# Most words a single `/next` request may draw. Selection samples by frequency
# and records (propagates) every word it does not present, so a high-rate
# lexicon needs many draws to surface one word worth asking. Caps the work (and
# the records written) per request; the request just returns fewer words.
_DRAW_BUDGET: int = 256


class DictionaryTranslation(BaseModel):
    """One dictionary's rendering of a word, as a safe HTML fragment."""

    dictionary: str  # Dictionary name.
    html: str  # Definitions/translations as a safe HTML fragment.


class Translation(BaseModel):
    """A word's translation, split per dictionary (empty if none found)."""

    word: str
    dictionaries: list[DictionaryTranslation]


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
    category: str | None = None
    """A `curated_words.category` code (see `NOT_TO_CHECK_CATEGORY_CODES`)
    reporting *why* the word should not be checked, e.g. `P` for a proper
    noun. Only meaningful alongside `response = "not_a_word"`; ignored
    otherwise. See `_record_not_to_check_vote`.
    """
    session_id: str | None = None
    """Open checking session to fold the answer into, if the client has one.

    The answer is persisted either way; the identifier only keeps the
    session's working memory and action count in step.
    """


_data: Data | None = None


def _data_dir() -> Path:
    """Get the Emmio data directory (`EMMIO_DATA_DIR`, default `~/.emmio`)."""
    return Path(os.environ.get("EMMIO_DATA_DIR", str(Path.home() / ".emmio")))


def get_data() -> Data:
    """Get the shared read-only data (frequency lists, dictionaries).

    Loaded once from the Emmio data directory (`EMMIO_DATA_DIR`, default
    `~/.emmio`). User-specific data comes from PostgreSQL instead.
    """
    global _data  # noqa: PLW0603  # pylint: disable=global-statement

    if _data is None:
        _data = Data.from_directory(_data_dir())
    return _data


def _config_or_404(config: dict | None, kind: str, artifact_id: str) -> dict:
    """Return the reassembled config dict or raise 404."""

    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown {kind} `{artifact_id}`.",
        )
    return config


def _lexicon_config_or_404(user_id: str, lexicon_id: str) -> dict:
    """Get a lexicon's reassembled config dict or raise 404."""

    return _config_or_404(
        postgres.get_lexicon_config(user_id, lexicon_id), "lexicon", lexicon_id
    )


def _learning_config_or_404(user_id: str, learning_id: str) -> dict:
    """Get a learning's reassembled config dict or raise 404."""

    return _config_or_404(
        postgres.get_learning_config(user_id, learning_id),
        "learning",
        learning_id,
    )


def _dictionary_configs(
    dictionaries: list[dict] | None,
) -> list[DictionaryUsageConfig]:
    """Parse a lexicon/learning's raw dictionary configs, preserving order."""
    return [DictionaryUsageConfig(**d) for d in dictionaries or []]


async def _translate(
    word: str,
    language: str,
    dictionaries: list[dict] | None,
    *,
    index: int | None = None,
    hide_word: bool = False,
) -> list[DictionaryTranslation]:
    """Look a word up, rendering each dictionary's output separately.

    When `index` is given, only the dictionary at that position in the
    configured list is queried; this lets the client load each dictionary
    independently and reveal them as they arrive, rather than waiting for the
    slowest one. `None` queries every configured dictionary. With `hide_word`
    the word is blanked out of the definitions, so they can serve as a learning
    prompt without revealing the answer.
    """

    configs: list[DictionaryUsageConfig] = _dictionary_configs(dictionaries)
    data: Data = get_data()
    if index is None:
        collection = data.get_dictionaries(configs)
    elif 0 <= index < len(configs):
        dictionary = data.get_dictionary(configs[index])
        collection = DictionaryCollection([dictionary] if dictionary else [])
    else:
        collection = DictionaryCollection([])

    with log_duration(f"translate `{word}` ({language})", logger):
        groups: list[
            tuple[str, list[Element]]
        ] = await collection.to_text_by_dictionary(
            word,
            Language.from_code(language),
            _DEFINITION_LANGUAGES,
            hide_word=hide_word,
        )
    return [
        DictionaryTranslation(dictionary=name, html=elements_to_html(elements))
        for name, elements in groups
    ]


class DictionaryInfo(BaseModel):
    """A configured dictionary the client can request a translation from."""

    index: int  # Position in the lexicon/learning's dictionary list.
    name: str  # Human-readable dictionary name.


def _dictionary_infos(dictionaries: list[dict] | None) -> list[DictionaryInfo]:
    """List the constructable dictionaries with their positional indices.

    Indices match those accepted by :py:func:`_translate`, so the client can
    fetch each dictionary's translation separately.
    """
    data: Data = get_data()
    infos: list[DictionaryInfo] = []
    for index, config in enumerate(_dictionary_configs(dictionaries)):
        dictionary = data.get_dictionary(config)
        if dictionary is not None:
            infos.append(
                DictionaryInfo(index=index, name=dictionary.get_name())
            )
    return infos


def _skip_decision(
    word: str,
    symbols: str | None,
    states: dict[str, tuple[str | None, bool | None]],
    recent: set[str],
) -> tuple[str, AnswerType, bool | None] | None:
    """Decide whether a drawn word should be auto-answered instead of asked.

    Mirrors the CLI's `do_skip`, using state already loaded into memory. A
    word is auto-answered (and so not presented) when it is outside the
    language's alphabet, flagged to skip, already "not a word", or was answered
    recently; otherwise it is presented (a new or stale word worth asking).

    :return: (response code, answer type, to_skip) to record, or `None` to
        present the word to the user
    """
    not_a_word: str = LexiconResponse.NOT_A_WORD.to_code()
    if symbols and any(symbol not in symbols for symbol in word):
        return not_a_word, AnswerType.ASSUME__NOT_A_WORD__ALPHABET, None
    if word not in states:
        return None  # Never seen anywhere: a new word to ask.
    response, to_skip = states[word]
    if to_skip:
        return (
            response or LexiconResponse.KNOW.to_code(),
            AnswerType.PROPAGATE__SKIP,
            to_skip,
        )
    if response == not_a_word:
        return not_a_word, AnswerType.PROPAGATE__NOT_A_WORD, None
    if word in recent and response is not None:
        return response, AnswerType.PROPAGATE__TIME, None
    return None  # Seen but stale: re-ask to refresh the estimate.


def _draw_batch(
    pick: Callable[[set[str]], str | None],
    drawn: set[str],
    limit: int,
    states: dict[str, tuple[str | None, bool | None]],
    recent: set[str],
    symbols: str | None,
    now: datetime,
) -> tuple[list[str], list[postgres.LexiconRecordRow]]:
    """Draw words to present, auto-answering the skippable ones.

    Every drawn word that is not presented is *recorded* with the answer it
    can be given automatically (already known/skipped/foreign/recently
    answered) rather than excluded, so the records stay a faithful sample and
    the rate is computed correctly.

    :param pick: the strategy's draw, given the words to exclude
    :param drawn: words to exclude from draws, grown as words are drawn
    :param limit: how many words to present
    :return: (words to present, auto-answer record rows to persist)
    """
    words: list[str] = []
    auto: list[postgres.LexiconRecordRow] = []
    for _ in range(_DRAW_BUDGET):
        if len(words) >= limit:
            break
        candidate: str | None = pick(drawn)
        if candidate is None:
            break
        drawn.add(candidate)
        decision = _skip_decision(candidate, symbols, states, recent)
        if decision is None:
            words.append(candidate)
            continue
        response, answer_type, to_skip = decision
        extra: dict = {"at": answer_type.to_code()}
        if to_skip is not None:
            extra["sk"] = to_skip
        auto.append((candidate, response, now, extra))
    return words, auto


def _propagated_stratum_answers(
    auto: list[postgres.LexiconRecordRow],
    frequency_list: FrequencyList,
    size: int,
    n_strata: int,
    selection: LexiconSelection,
) -> list[StratumAnswer]:
    """Build the chart-ready points for words `_draw_batch` auto-answered.

    Mirrors the trajectory replay's own filter (`get_lexicon_rate_
    trajectory`): only know/don't-know codes place a dot, so a `not_a_word`
    propagation (no "know" boolean to plot) is silently skipped, same as
    there.
    """
    if selection != LexiconSelection.STRATIFIED:
        return []
    know: str = LexiconResponse.KNOW.to_code()
    know_class: str = LexiconResponse.KNOW_SEMANTIC_CLASS.to_code()
    dont: str = LexiconResponse.DONT.to_code()
    answers: list[StratumAnswer] = []
    for word, code, _when, _extra in auto:
        if code not in (know, know_class, dont):
            continue
        index: int = frequency_list.get_index(word)
        if index < 0:
            continue
        answers.append(
            StratumAnswer(
                stratum=stratum_of_rank(index + 1, size, n_strata),
                know=code != dont,
            )
        )
    return answers


class OpenedSession(BaseModel):
    """Identifier of a freshly opened session."""

    session_id: str


@app.post(
    "/api/v1/me/lexicons/{lexicon_id}/sessions",
    status_code=status.HTTP_201_CREATED,
)
def open_lexicon_session(
    lexicon_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> OpenedSession:
    """Open a checking session on the lexicon.

    The session holds the strategy's working memory between requests, so
    draws stay cheap on large frequency lists, and it is written to the
    lexicon's session log when closed. Pass its identifier to `/next` and
    `/answer`; an unknown or expired identifier reopens the session
    transparently, so the client never has to handle a lost one.
    """
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    frequency_list: FrequencyList = _frequency_list_or_error(config, lexicon_id)
    curated: tuple[int, dict[int, list[str]]] | None = (
        _curated_pool_for_lexicon(config)
    )
    try:
        session = LEXICON_SESSIONS.open(
            user_id,
            lexicon_id,
            config["language"],
            LexiconSelection(config["selection"]),
            frequency_list,
            n_strata=curated[0] if curated else DEFAULT_N_STRATA,
            curated_words_by_stratum=curated[1] if curated else None,
        )
    except NotImplementedError as error:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(error)
        ) from error
    return OpenedSession(session_id=session.session_id)


@app.post(
    "/api/v1/me/lexicons/{lexicon_id}/sessions/{session_id}/close",
    status_code=status.HTTP_204_NO_CONTENT,
)
def close_lexicon_session(
    lexicon_id: str,
    session_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> None:
    """Close the checking session, writing its log row.

    Idempotent: closing an unknown or already-closed session is a no-op, so
    client retries are safe. A session that is never closed is finalized when
    it expires or the server shuts down.
    """
    _lexicon_config_or_404(user_id, lexicon_id)
    LEXICON_SESSIONS.close(user_id, lexicon_id, session_id)


@app.get("/api/v1/me/lexicons/{lexicon_id}/next")
def get_next_lexicon_words(
    lexicon_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    count: int = 1,
    exclude: Annotated[list[str] | None, Query()] = None,
    session_id: str | None = None,
) -> NextWords:
    """Get the next words to check in the authenticated user's lexicon.

    Words are drawn by the lexicon's strategy. Every drawn word that is not
    presented is *recorded* with the answer it can be given automatically
    (already known/skipped/foreign/recently answered) rather than excluded, so
    the records stay a faithful frequency-weighted sample and the rate is
    computed correctly. `count` requests how many words to present; `exclude`
    lists words already queued on the client.

    With a `session_id` (from opening a checking session) the draw comes from
    the session's working memory, so it stays cheap on large lists; an unknown
    or expired identifier transparently reopens the session. Without one, the
    selection state is rebuilt from the database on every request.
    """
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    frequency_list: FrequencyList = _frequency_list_or_error(config, lexicon_id)
    language: str = config["language"]
    selection: LexiconSelection = LexiconSelection(config["selection"])
    symbols: str | None = Language.from_code(language).get_symbols()
    curated: tuple[int, dict[int, list[str]]] | None = (
        _curated_pool_for_lexicon(config)
    )
    n_strata: int = curated[0] if curated else DEFAULT_N_STRATA

    limit: int = max(1, min(count, _BATCH_MAX))
    drawn: set[str] = set(exclude or [])
    now: datetime = datetime.now(UTC)

    try:
        if session_id is not None:
            # Session path: draw from the session's working memory instead of
            # rebuilding selection state from the database.
            session: LexiconCheckSession = LEXICON_SESSIONS.acquire(
                user_id,
                lexicon_id,
                session_id,
                language,
                selection,
                frequency_list,
                n_strata=n_strata,
                curated_words_by_stratum=curated[1] if curated else None,
            )
            with session.lock:
                words, auto = _draw_batch(
                    session.selector.next_word,
                    drawn,
                    limit,
                    session.states,
                    session.recent,
                    symbols,
                    now,
                )
                if auto:
                    postgres.save_lexicon(
                        user_id, lexicon_id, language, auto, []
                    )
                    for word, code, _when, extra in auto:
                        session.note_auto(
                            word, code, to_skip=(extra or {}).get("sk")
                        )
        else:
            states: dict[str, tuple[str | None, bool | None]] = (
                postgres.get_language_word_states(user_id, language)
            )
            recent: set[str] = postgres.get_recently_answered(user_id, language)
            selector_states: dict[str, tuple[str | None, bool | None]] = (
                postgres.get_lexicon_selector_states(user_id, lexicon_id)
            )
            # "top" walks the list in rank order and never re-asks an answered
            # word, so exclude everything already recorded; sampling
            # strategies re-sample, so they rely on `_skip_decision` instead.
            if selection == LexiconSelection.TOP:
                drawn |= postgres.get_answered_words(user_id, lexicon_id)
            words, auto = _draw_batch(
                lambda pool: select_next_word(
                    frequency_list,
                    pool,
                    selection,
                    selector_states,
                    n_strata,
                    curated[1] if curated else None,
                ),
                drawn,
                limit,
                states,
                recent,
                symbols,
                now,
            )
            if auto:
                postgres.save_lexicon(user_id, lexicon_id, language, auto, [])
    except NotImplementedError as error:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(error)
        ) from error
    answers = postgres.get_last_lexicon_answers(user_id, lexicon_id, words)
    cards: list[WordCard] = _word_cards(
        words, answers, _LEXICON_RESPONSE_LABELS
    )
    # Attach per-word strategy context for the check page's status panel: the
    # word's frequency rank, and its stratum under the stratified strategy.
    size: int = len(frequency_list)
    for card in cards:
        index: int = frequency_list.get_index(card.word)
        if index < 0:
            continue
        card.rank = index + 1
        if selection == LexiconSelection.STRATIFIED:
            card.stratum = stratum_of_rank(card.rank, size, n_strata)
    return NextWords(
        language=language,
        words=cards,
        selection=selection,
        list_size=size,
        strata=(n_strata if selection == LexiconSelection.STRATIFIED else None),
        propagated=_propagated_stratum_answers(
            auto, frequency_list, size, n_strata, selection
        ),
    )


_NOT_TO_CHECK_CODES: frozenset[str] = frozenset(
    NOT_TO_CHECK_CATEGORY_CODES.values()
)


def _record_not_to_check_vote(
    word: str,
    category_code: str,
    frequency_list_config: dict | None,
    language: str,
    user_id: str,
) -> None:
    """Feed a "not to check" judgment into the shared curated panel.

    Mirrors `LexiconChecker._record_not_to_check_vote` (the CLI's
    equivalent) — see there for why this writes straight into
    `curated_words`/`curated_word_records` instead of a separate
    mechanism: curation is a property of the list, not the learner, so a
    web check-page report and an `emmio curate` vote are the same kind of
    thing. Best-effort: silently does nothing if the lexicon has no
    frequency list configured, or the word cannot be placed in it.
    """
    if frequency_list_config is None:
        return
    list_usage_config: ListUsageConfig = ListUsageConfig(
        **frequency_list_config
    )
    frequency_list: FrequencyList | None = get_data().get_frequency_list(
        list_usage_config
    )
    if frequency_list is None:
        return
    index: int = frequency_list.get_index(word)
    if index < 0:
        return

    frequency_list_id: str = frequency_list_identifier(list_usage_config)
    list_id: int = postgres.create_curated_list(
        language,
        frequency_list_id,
        f"{Language.from_code(language).get_name()} {frequency_list_id} "
        "Curated",
    )
    n_strata: int = postgres.get_curated_list_n_strata(list_id)
    stratum: int = stratum_of_rank(index + 1, len(frequency_list), n_strata)
    postgres.promote_fallback_word(list_id, word, stratum)
    postgres.record_curation_vote(list_id, word, category_code, user_id)


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
    if request.category is not None and response == LexiconResponse.NOT_A_WORD:
        if request.category not in _NOT_TO_CHECK_CODES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid category `{request.category}`.",
            )
        _record_not_to_check_vote(
            request.word,
            request.category,
            config["frequency_list"],
            config["language"],
            user_id,
        )
    now: datetime = datetime.now(UTC)
    record: postgres.LexiconRecordRow = (
        request.word,
        response.to_code(),
        now,
        {"sk": True} if request.to_skip else None,
    )
    postgres.save_lexicon(user_id, lexicon_id, config["language"], [record], [])
    if request.session_id is not None:
        LEXICON_SESSIONS.note_answer(
            user_id,
            lexicon_id,
            request.session_id,
            request.word,
            response.to_code(),
            to_skip=True if request.to_skip else None,
            when=now,
        )


def _curated_pool_for_lexicon(
    config: dict,
) -> tuple[int, dict[int, list[str]]] | None:
    """Resolve a curated-backed lexicon's panel, keyed by stratum.

    Returns `None` for an ordinary (non-curated) lexicon. A curated
    lexicon's `frequency_list.curated` flag was already validated against
    an existing curated list at creation time (`create_lexicon`); a missing
    list here (e.g. deleted afterward) is treated as "not curated" rather
    than an error, falling back to raw-list serving.

    :return: `(n_strata, words_by_stratum)`, or `None`
    """
    frequency_list_config: dict | None = config["frequency_list"]
    if frequency_list_config is None or not frequency_list_config.get(
        "curated"
    ):
        return None
    frequency_list_id: str = frequency_list_identifier(
        ListUsageConfig(**frequency_list_config)
    )
    curated_list_id: int | None = postgres.get_curated_list_id(
        config["language"], frequency_list_id
    )
    if curated_list_id is None:
        return None
    return (
        postgres.get_curated_list_n_strata(curated_list_id),
        postgres.get_curated_real_words_by_stratum(curated_list_id),
    )


def _frequency_list_or_error(config: dict, lexicon_id: str) -> FrequencyList:
    """Load the lexicon's configured frequency list, or raise an HTTP error.

    The model-based rate estimators place every word by frequency rank,
    so they cannot run without the list: no list configured is a client
    error, a configured list that fails to load is a server one.
    """
    if config["frequency_list"] is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lexicon `{lexicon_id}` has no frequency list configured.",
        )
    frequency_list: FrequencyList | None = get_data().get_frequency_list(
        ListUsageConfig(**config["frequency_list"])
    )
    if frequency_list is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configured frequency list could not be loaded.",
        )
    return frequency_list


class RateEstimate(BaseModel):
    """Strategy-aware estimate of the vocabulary rate and its error."""

    rate: float | None
    """Estimated rate, or `None` if not enough data yet."""

    sd: float | None
    """Standard deviation of the estimate."""

    method: RateEstimator
    """Estimator used.

    Possible values: `frequency`, `stratified`, `threshold` or `logistic`.
    """

    achieved: bool
    """Whether the trailing 3-month precision goal is currently met."""

    recheck_available_at: datetime | None
    """When the "Check" button unlocks again, or `None` if available now."""


@app.get("/api/v1/me/lexicons/{lexicon_id}/rate-estimate")
def get_lexicon_rate_estimate(
    lexicon_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> RateEstimate:
    """Estimate the lexicon's vocabulary rate with its standard deviation.

    Dispatches to the estimator matching the lexicon's selection strategy, the
    same as the stats/list endpoints' `rate` field (`_row_rate_estimate`) —
    unlike the windowed rate history (`compute_lexicon_rate`, behind
    `/lexicons/history`), which applies the frequency-weighted sliding window
    regardless of strategy and is unbiased only over frequency-weighted draws.
    Refreshed by the check page after every answer, which also uses `achieved`
    to end the session and return to the lexicon list once the
    trailing-window precision goal is met.
    """
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    selection: LexiconSelection = LexiconSelection(config["selection"])
    method: RateEstimator | None = RATE_ESTIMATOR_BY_SELECTION.get(selection)
    if method is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"No rate estimator for selection `{selection}`.",
        )

    curated: tuple[int, dict[int, list[str]]] | None = (
        _curated_pool_for_lexicon(config)
    )
    n_strata: int = curated[0] if curated else DEFAULT_N_STRATA
    curated_pool: dict[int, list[str]] | None = curated[1] if curated else None

    frequency_list: FrequencyList | None = None
    dated_records: list[tuple[datetime, str, str]] = (
        postgres.get_lexicon_dated_record_log(user_id, lexicon_id)
    )
    if method == RateEstimator.FREQUENCY:
        estimate: tuple[float, float] | None = estimate_rate_with_sd(
            selection,
            sequence=postgres.get_lexicon_answer_sequence(user_id, lexicon_id),
        )
    elif method == RateEstimator.STRATIFIED:
        frequency_list = _frequency_list_or_error(config, lexicon_id)
        estimate = _stratified_rate_windowed_or_full(
            user_id,
            lexicon_id,
            selection,
            frequency_list,
            dated_records,
            n_strata,
            curated_pool,
        )
    else:
        # The model-based estimators place every word by frequency rank, so
        # they need the lexicon's frequency list and the same lexicon-scoped
        # states that seed word selection: the estimate must reflect this
        # lexicon's own sample, not answers collected under sibling lexicons'
        # strategies.
        frequency_list = _frequency_list_or_error(config, lexicon_id)
        states: dict[str, tuple[str | None, bool | None]] = (
            postgres.get_lexicon_selector_states(user_id, lexicon_id)
        )
        estimate = estimate_rate_with_sd(selection, frequency_list, states)

    rate, sd = _rate_and_sd(estimate)
    goal: LexiconGoalState = compute_lexicon_goal_state(
        selection, frequency_list, dated_records, None, n_strata, curated_pool
    )
    return RateEstimate(
        rate=rate,
        sd=sd,
        method=method,
        achieved=goal.achieved,
        recheck_available_at=goal.recheck_available_at,
    )


class TrajectoryPoint(BaseModel):
    """The rate estimate after a prefix of the answer history."""

    queries: int
    """1-based number of answers the estimate is computed over."""

    rate: float | None
    """Estimated rate, or `None` if not enough data at this point."""

    sd: float | None
    """Standard deviation of the estimate."""


class RateTrajectory(BaseModel):
    """The estimate trajectory over the whole recorded answer history."""

    method: RateEstimator
    """Estimator used at every checkpoint."""

    total: int
    """Number of answers recorded in the lexicon."""

    checkpoints: list[TrajectoryPoint]
    """Estimates at evenly spaced points of the history, oldest first."""

    n_strata: int | None = None
    """Total number of strata, when the selection is `stratified`."""

    strata: list[StratumAnswer] | None = None
    """Chronological know/don't-know answers with their strata.

    Only for the `stratified` selection; answers to words outside the
    frequency list (invisible to the selector) are skipped.
    """


MAX_TRAJECTORY_CHECKPOINTS: int = 200
"""Upper bound on trajectory checkpoints.

Enough points for a smooth line on screen, few enough that replaying a
long answer history stays a single fast request.
"""


def _prefer_windowed_estimates(
    checkpoints: list[int],
    estimates: list[tuple[float, float] | None],
    windowed_queries: list[int],
    windowed_rates: list[float],
    windowed_sds: list[float],
) -> list[tuple[float, float] | None]:
    """Overlay a windowed rate history onto a full-history replay.

    Once the moving window first reaches its target SD, its estimate
    replaces the full-history one at every checkpoint from that answer on;
    earlier checkpoints keep the full-history replay's own estimate, the
    same early-session fallback `_stratified_rate_windowed_or_full` uses for
    the live rate.

    :param checkpoints: 1-based answer numbers the replay stopped at
    :param estimates: the replay's own per-checkpoint (r̂, SD), index-aligned
        with `checkpoints`
    :param windowed_queries: 1-based answer numbers of the windowed history's
        own points, strictly increasing
    :param windowed_rates: the windowed history's rates, index-aligned with
        `windowed_queries`
    :param windowed_sds: the windowed history's SDs, index-aligned with
        `windowed_queries`
    """
    result: list[tuple[float, float] | None] = []
    pos: int = 0
    n: int = len(windowed_queries)
    for checkpoint, estimate in zip(checkpoints, estimates, strict=True):
        while pos < n and windowed_queries[pos] <= checkpoint:
            pos += 1
        result.append(
            (windowed_rates[pos - 1], windowed_sds[pos - 1])
            if pos > 0
            else estimate
        )
    return result


@app.get("/api/v1/me/lexicons/{lexicon_id}/rate-trajectory")
def get_lexicon_rate_trajectory(
    lexicon_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> RateTrajectory:
    """Replay the rate estimate over the lexicon's whole answer history.

    Re-runs the same strategy-matched estimator `rate-estimate` uses after
    every `step` answers of the recorded log, so the check page can seed
    its convergence chart with the history and then grow it live from the
    per-answer estimates. For `stratified`, checkpoints from the moving
    window's first achieved point onward use that windowed estimate instead
    (`_prefer_windowed_estimates`), matching `rate-estimate`'s own
    windowed-or-full fallback.
    """
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    selection: LexiconSelection = LexiconSelection(config["selection"])
    method: RateEstimator | None = RATE_ESTIMATOR_BY_SELECTION.get(selection)
    if method is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"No rate estimator for selection `{selection}`.",
        )

    curated: tuple[int, dict[int, list[str]]] | None = (
        _curated_pool_for_lexicon(config)
    )
    n_strata: int = curated[0] if curated else DEFAULT_N_STRATA
    curated_pool: dict[int, list[str]] | None = curated[1] if curated else None

    frequency_list: FrequencyList | None = None
    if method != RateEstimator.FREQUENCY:
        frequency_list = _frequency_list_or_error(config, lexicon_id)

    dated_records: list[tuple[datetime, str, str]] = (
        postgres.get_lexicon_dated_record_log(user_id, lexicon_id)
    )
    records: list[tuple[str, str]] = [
        (word, code) for _, word, code in dated_records
    ]
    step: int = max(1, -(-len(records) // MAX_TRAJECTORY_CHECKPOINTS))
    checkpoints, estimates = replay(
        records,
        selection,
        frequency_list,
        step,
        n_strata=n_strata,
        curated_words_by_stratum=curated_pool,
    )

    if method == RateEstimator.STRATIFIED:
        # Once the moving window first reaches its target SD, its narrower
        # estimate replaces the full-history replay from that answer on —
        # the trajectory's own version of `_stratified_rate_windowed_or_full`,
        # so the chart's last point always agrees with the live rate.
        w_queries, _, w_rates, w_sds = compute_rate_history(
            selection,
            frequency_list,
            dated_records,
            n_strata=n_strata,
            curated_words_by_stratum=curated_pool,
        )
        estimates = _prefer_windowed_estimates(
            checkpoints, estimates, w_queries, w_rates, w_sds
        )

    # The check page's stratum wheel: every know/don't-know answer with its
    # word's stratum, in answer order.
    strata: list[StratumAnswer] | None = None
    if selection == LexiconSelection.STRATIFIED and frequency_list is not None:
        know: str = LexiconResponse.KNOW.to_code()
        know_class: str = LexiconResponse.KNOW_SEMANTIC_CLASS.to_code()
        dont: str = LexiconResponse.DONT.to_code()
        size: int = len(frequency_list)
        strata = []
        for word, code in records:
            if code not in (know, know_class, dont):
                continue
            index: int = frequency_list.get_index(word)
            if index < 0:
                continue
            strata.append(
                StratumAnswer(
                    stratum=stratum_of_rank(index + 1, size, n_strata),
                    know=code != dont,
                )
            )

    return RateTrajectory(
        method=method,
        total=len(records),
        checkpoints=[
            TrajectoryPoint(queries=queries, rate=rate, sd=sd)
            for queries, (rate, sd) in zip(
                checkpoints, map(_rate_and_sd, estimates), strict=True
            )
        ],
        n_strata=(
            DEFAULT_N_STRATA
            if selection == LexiconSelection.STRATIFIED
            else None
        ),
        strata=strata,
    )


@app.post("/api/v1/me/lexicons/{lexicon_id}/undo")
def undo_lexicon_answer(
    lexicon_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> NextWord:
    """Undo the most recent answer in the lexicon, returning its word.

    The word becomes un-answered (and selectable) again, so a mis-click can be
    corrected by re-answering it.
    """
    _lexicon_config_or_404(user_id, lexicon_id)
    return NextWord(
        word=postgres.delete_last_lexicon_record(user_id, lexicon_id)
    )


@app.get("/api/v1/me/lexicons/{lexicon_id}/dictionaries")
def get_lexicon_dictionaries(
    lexicon_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> list[DictionaryInfo]:
    """List a lexicon's dictionaries so the client can load each separately."""
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    return _dictionary_infos(config["dictionaries"])


@app.get("/api/v1/me/lexicons/{lexicon_id}/translation")
async def get_lexicon_translation(
    lexicon_id: str,
    word: str,
    user_id: Annotated[str, Depends(get_current_user)],
    index: int | None = None,
) -> Translation:
    """Get a word's translation from the lexicon's configured dictionaries.

    `index` optionally restricts the result to the single dictionary at that
    position (see `/dictionaries`), so the client can load each dictionary
    independently and reveal them as they arrive.
    """
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    return Translation(
        word=word,
        dictionaries=await _translate(
            word, config["language"], config["dictionaries"], index=index
        ),
    )


class Sentence(BaseModel):
    """An example sentence for a word, as a safe HTML fragment, or `None`."""

    word: str
    sentence: str | None
    translation: str | None = None
    """A translation of the sentence (learning only), else `None`."""
    sentence_id: int | None = None
    """The example's id (learning only), recorded with the answer."""


@app.get("/api/v1/me/lexicons/{lexicon_id}/sentence")
def get_lexicon_sentence(
    lexicon_id: str,
    word: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> Sentence:
    """Get one example sentence for a word (slow lookup, kept off `/next`)."""
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    return Sentence(
        word=word,
        sentence=_sentence_html(
            word, config["language"], config.get("sentences")
        ),
    )


# Words per page for a paginated word list (both this lexicon's "see these
# words" links and the curated-list review table below). Same order of
# magnitude as a stratum's target panel size (`DEFAULT_N_C` in
# `emmio.lexicon.curation`), so a page is a natural, skimmable chunk rather
# than an arbitrary round number.
_WORDS_PAGE_SIZE_DEFAULT: int = 100
_WORDS_PAGE_SIZE_MAX: int = 500


class LexiconStats(BaseModel):
    """Details and statistics for a single lexicon."""

    lexicon_id: str
    language: str
    selection: str | None
    frequency_list_name: str | None
    """Human-readable name of the frequency list words are drawn from.

    `None` for a lexicon with no frequency list (e.g. an alphabet lexicon).
    """
    words: int  # Distinct words checked.
    known: int  # Words whose last answer was "know".
    dont_know: int  # Words whose last answer was "don't know".
    precision: int  # Total "don't know" answers (the rate's precision).
    dont_last_week: int  # "Don't know" answers in the last 7 days.
    rate: float | None  # Vocabulary rate, or None if not enough data.
    sd: float | None  # Standard deviation of the rate estimate.
    trailing_rate: float | None
    """Vocabulary rate over the trailing 3 months only, or `None`.

    The same estimate `achieved` is judged against (`LexiconGoalState.rate`):
    unlike `rate`, a know/don't-know answer older than `WINDOW_DAYS` does not
    count, so this reflects only knowledge still considered fresh. `None`
    while that trailing window alone does not yet support an estimate, even
    if `rate` (over the whole history) does.
    """
    trailing_sd: float | None  # Standard deviation of `trailing_rate`.
    is_main: bool  # Main lexicon for its language.
    achieved: bool  # Whether the trailing 3-month precision goal is met.
    check_available: bool  # Whether checking is allowed right now.
    recheck_available_at: datetime | None  # When "Check" unlocks, if not now.


@app.get("/api/v1/me/lexicons/{lexicon_id}/stats")
def get_lexicon_stats(
    lexicon_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> LexiconStats:
    """Get details and statistics for one lexicon.

    Loads the lexicon's records to compute the vocabulary rate (with the
    estimator matching the selection strategy, as in `rate-estimate`), so it
    is heavier than the list endpoint; intended for a single-lexicon view.
    """
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    # The path is vestigial (records live in the database); any value works.
    lexicon: Lexicon = Lexicon.from_config(
        Path(), lexicon_id, LexiconConfig(**config), user_id
    )
    now: datetime = datetime.now(UTC)
    known: int = sum(
        knowledge.knowing
        in (LexiconResponse.KNOW, LexiconResponse.KNOW_SEMANTIC_CLASS)
        for knowledge in lexicon.words.values()
    )
    dont_know: int = sum(
        knowledge.knowing == LexiconResponse.DONT
        for knowledge in lexicon.words.values()
    )
    estimate: tuple[float, float] | None = _row_rate_estimate(
        user_id,
        lexicon_id,
        config["selection"],
        config["frequency_list"],
        lambda: postgres.get_lexicon_answer_sequence(user_id, lexicon_id),
        language=config["language"],
    )
    rate, sd = _rate_and_sd(estimate)
    curated: tuple[int, dict[int, list[str]]] | None = (
        _curated_pool_for_lexicon(config)
    )
    goal: LexiconGoalState = compute_lexicon_goal_state(
        LexiconSelection(config["selection"]),
        _frequency_list_or_none(config["frequency_list"]),
        postgres.get_lexicon_dated_record_log(user_id, lexicon_id),
        now,
        curated[0] if curated else DEFAULT_N_STRATA,
        curated[1] if curated else None,
    )
    return LexiconStats(
        lexicon_id=lexicon_id,
        language=config["language"],
        selection=config["selection"],
        frequency_list_name=_frequency_list_name(
            get_data(), config.get("frequency_list")
        ),
        words=len(lexicon),
        known=known,
        dont_know=dont_know,
        precision=lexicon.count_unknowns(),
        dont_last_week=lexicon.count_unknowns(now - timedelta(days=7), now),
        rate=rate,
        sd=sd,
        trailing_rate=goal.rate,
        trailing_sd=goal.sd,
        is_main=postgres.is_main_lexicon(user_id, lexicon_id),
        achieved=goal.achieved,
        check_available=goal.check_available,
        recheck_available_at=goal.recheck_available_at,
    )


# Response codes grouped the same way `get_lexicon_stats` sums them, so a
# page's word list always matches the count the user clicked through from.
# `"all"` maps to `None` (no filter) rather than being left out, so it is
# still a member of this dict — `response not in ...` is how an actually
# unsupported value is told apart from the "no filter" case.
_LEXICON_WORD_RESPONSE_GROUPS: dict[str, frozenset[str] | None] = {
    "all": None,
    "know": frozenset(
        {
            LexiconResponse.KNOW.to_code(),
            LexiconResponse.KNOW_SEMANTIC_CLASS.to_code(),
        }
    ),
    "dont": frozenset({LexiconResponse.DONT.to_code()}),
}


class LexiconWordEntry(BaseModel):
    """One word in a lexicon, with its current response and when seen."""

    word: str
    response_label: str | None  # E.g. "know", "don't know"; `None` if unset.
    last_seen: datetime | None


class LexiconWordsPage(BaseModel):
    """One page of a lexicon's words matching a response group.

    Backs the dedicated lexicon word-list page's "All"/"Know"/"Don't know"
    filter.
    """

    words: list[LexiconWordEntry]
    total: int  # Total words in the group, across every page.
    page: int
    page_size: int


@app.get("/api/v1/me/lexicons/{lexicon_id}/words")
def get_lexicon_words(
    lexicon_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    response: str,
    page: int = 1,
    page_size: int = _WORDS_PAGE_SIZE_DEFAULT,
) -> LexiconWordsPage:
    """Get one page of a lexicon's words currently answered `response`.

    `response` is `all`, `know` (last answer "know" or "know class"), or
    `dont` (last answer "don't know") — the latter two the same grouping
    `get_lexicon_stats` sums into its "Known"/"Don't know" counts.
    `page`/`page_size` are clamped rather than rejected, matching
    `/curation/{language}/{id}/words`.
    """
    _lexicon_config_or_404(user_id, lexicon_id)
    if response not in _LEXICON_WORD_RESPONSE_GROUPS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported response `{response}`. Choose one of: "
                f"{', '.join(sorted(_LEXICON_WORD_RESPONSE_GROUPS))}."
            ),
        )
    codes: frozenset[str] | None = _LEXICON_WORD_RESPONSE_GROUPS[response]
    page = max(1, page)
    page_size = max(1, min(page_size, _WORDS_PAGE_SIZE_MAX))
    offset: int = (page - 1) * page_size
    rows = postgres.get_lexicon_words_by_response(
        user_id, lexicon_id, codes, offset=offset, limit=page_size
    )
    return LexiconWordsPage(
        words=[
            LexiconWordEntry(
                word=word,
                response_label=_LEXICON_RESPONSE_LABELS.get(code)
                if code
                else None,
                last_seen=last_seen,
            )
            for word, code, last_seen in rows
        ],
        total=postgres.count_lexicon_words_by_response(
            user_id, lexicon_id, codes
        ),
        page=page,
        page_size=page_size,
    )


class LanguageRate(BaseModel):
    """A language's level: the rate of its main lexicon."""

    language: str
    lexicon_id: str  # The main lexicon the rate comes from.
    selection: str | None  # The main lexicon's selection strategy, if known.
    rate: float | None  # Vocabulary rate, or None if not enough data.
    sd: float | None  # Standard deviation of the rate estimate.
    check_available: bool  # Whether checking is allowed right now.
    recheck_available_at: datetime | None  # When "Check" unlocks, if not now.


class LanguageSummary(BaseModel):
    """A language's main-lexicon identity, without its rate estimate.

    The cheap counterpart to `LanguageRate`: no per-lexicon rate estimate is
    computed, so this is safe to fetch first and render immediately.
    """

    language: str
    lexicon_id: str
    selection: str | None


@app.get("/api/v1/me/languages/summary")
def get_my_languages_summary(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[LanguageSummary]:
    """List the user's main-lexicon languages, without the rate estimate.

    A fast counterpart to `/me/languages`: it skips `_row_rate_estimate`
    entirely (see its cache-miss cost note above `_row_rate_estimate`), so
    the dashboard can fetch this first and render the languages table
    immediately, then fetch `/me/languages` to fill in the rate, level, and
    check-availability columns once they're ready.
    """
    return [
        LanguageSummary(
            language=language, lexicon_id=lexicon_id, selection=selection
        )
        for language, lexicon_id, selection, _ in postgres.get_main_lexicons(
            user_id
        )
    ]


@app.get("/api/v1/me/languages")
def get_my_languages(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[LanguageRate]:
    """List the user's languages and their level (the main lexicon's rate).

    The rate comes from the estimator matching each main lexicon's selection
    strategy, as in the single-lexicon `rate-estimate` endpoint. Both the
    rate (`_row_rate_estimate`) and the goal state behind `check_available`
    (`_lexicon_goal_state`) are cached per lexicon, so a repeat table load
    with no new answers touches neither a lexicon's answer sequence nor its
    record log — just the two whole-user queries below plus a handful of
    cache-dict lookups, instead of pulling a user's full (potentially
    tens-of-thousands-of-rows) answer history on every load regardless of
    whether the cache could have answered without it.
    """
    version: int | None = postgres.get_last_lexicon_record_id(user_id)
    now: datetime = datetime.now(UTC)
    rates: list[LanguageRate] = []
    for (
        language,
        lexicon_id,
        selection,
        frequency_list_config,
    ) in postgres.get_main_lexicons(user_id):
        estimate: tuple[float, float] | None = _row_rate_estimate(
            user_id,
            lexicon_id,
            selection,
            frequency_list_config,
            lambda lid=lexicon_id: postgres.get_lexicon_answer_sequence(
                user_id, lid
            ),
            version,
            language=language,
        )
        rate, sd = _rate_and_sd(estimate)
        curated: tuple[int, dict[int, list[str]]] | None = (
            _curated_pool_for_lexicon(
                {"language": language, "frequency_list": frequency_list_config}
            )
        )
        goal: LexiconGoalState = _lexicon_goal_state(
            user_id,
            lexicon_id,
            LexiconSelection(selection)
            if selection
            else LexiconSelection.UNKNOWN,
            _frequency_list_or_none(frequency_list_config),
            now,
            version,
            n_strata=curated[0] if curated else DEFAULT_N_STRATA,
            curated_words_by_stratum=curated[1] if curated else None,
        )
        rates.append(
            LanguageRate(
                language=language,
                lexicon_id=lexicon_id,
                selection=selection,
                rate=rate,
                sd=sd,
                check_available=goal.check_available,
                recheck_available_at=goal.recheck_available_at,
            )
        )
    rates.sort(
        key=lambda r: r.rate if r.rate is not None else float("-inf"),
        reverse=True,
    )
    return rates


class LanguageHistoryPoint(BaseModel):
    """One windowed rate estimate in a language's history."""

    date: datetime  # The estimation window's end.
    rate: float
    sd: float


class LanguageHistory(BaseModel):
    """A language's windowed rate history, for the dashboard chart."""

    language: str
    points: list[LanguageHistoryPoint]


HistoryInterval = Literal["month", "year"]


def _interval_start(date: datetime, interval: HistoryInterval) -> datetime:
    date = date.replace(hour=0, minute=0, second=0, microsecond=0, day=1)
    return date.replace(month=1) if interval == "year" else date


def _next_interval(date: datetime, interval: HistoryInterval) -> datetime:
    if interval == "year":
        return date.replace(year=date.year + 1)
    return (
        date.replace(year=date.year + 1, month=1)
        if date.month == 12
        else date.replace(month=date.month + 1)
    )


def _grid_points(
    date_ranges: list[tuple[datetime, datetime]],
    rates: list[float],
    sds: list[float],
    interval: HistoryInterval = "month",
) -> list[LanguageHistoryPoint]:
    """Resample a windowed rate history onto a uniform monthly or yearly grid.

    `compute_rate_history` emits a new window every time the log first
    supports the required precision again — for a regular reviewer that can
    be weekly or even more often, and always at whatever date the log
    happens to land on, not evenly spaced. Snapping each raw point's own
    date to its containing month (or year) would still plot at irregular x
    positions within each interval; instead, every point on the chart sits
    at a first-of-interval checkpoint, valued at the latest window that had
    already closed before that checkpoint — the window moves from one
    checkpoint to the next rather than following the log. The grid stops at
    the calendar interval of the last raw point rather than the real
    current one, so a lexicon that has gone quiet does not grow an
    ever-longer flat tail of checkpoints repeating its last known rate. A
    history under two intervals returns every raw point instead, the same
    threshold the chart's own tick labels fall back at, so a young lexicon
    still gets a legible line rather than one lone point.
    """
    raw = [
        LanguageHistoryPoint(date=end, rate=rate, sd=sd)
        for (_, end), rate, sd in zip(date_ranges, rates, sds, strict=True)
    ]
    if len(raw) < 2:
        return raw

    grid: list[LanguageHistoryPoint] = []
    index = 0  # Latest raw point known to end before `boundary`.
    boundary = _interval_start(raw[0].date, interval)
    last_boundary = _interval_start(raw[-1].date, interval)
    while boundary <= last_boundary:
        while index + 1 < len(raw) and raw[index + 1].date < boundary:
            index += 1
        if raw[index].date < boundary:
            grid.append(
                LanguageHistoryPoint(
                    date=boundary, rate=raw[index].rate, sd=raw[index].sd
                )
            )
        boundary = _next_interval(boundary, interval)
    return grid if len(grid) >= 2 else raw


@app.get("/api/v1/me/lexicons/history")
def get_lexicons_history(
    user_id: Annotated[str, Depends(get_current_user)],
    interval: HistoryInterval = "month",
) -> list[LanguageHistory]:
    """List the windowed rate history of the user's main lexicons.

    Each language's points come from the windowed, strategy-matched estimator
    (`compute_rate_history`), resampled onto a uniform first-of-`interval`
    grid (`_grid_points`) once there is more than one interval of history.
    Languages whose estimator has no windowed history yet (threshold,
    logistic) and lexicons whose configured frequency list cannot be loaded
    are omitted. The client (the dashboard's history chart, the same
    mechanism the lexicon check page's convergence chart uses) draws the
    lines itself, one per language, coloring each from its own chart palette
    rather than the language's own display color.
    """
    result: list[LanguageHistory] = []
    for (
        language_code,
        lexicon_id,
        selection_code,
        list_config,
    ) in postgres.get_main_lexicons(user_id):
        try:
            language: Language = Language.from_code(language_code)
        except LanguageNotFoundError:
            continue
        # Lexicons imported before selection strategies were recorded are
        # frequency-weighted ones.
        selection: LexiconSelection = (
            LexiconSelection(selection_code)
            if selection_code
            else LexiconSelection.FREQUENCY
        )
        frequency_list: FrequencyList | None = None
        if (
            RATE_ESTIMATOR_BY_SELECTION.get(selection)
            != RateEstimator.FREQUENCY
        ):
            if not list_config:
                continue
            frequency_list = get_data().get_frequency_list(
                ListUsageConfig(**list_config)
            )
            if frequency_list is None:
                continue
        records: list[tuple[datetime, str, str]] = (
            postgres.get_lexicon_dated_record_log(user_id, lexicon_id)
        )
        if not records:
            continue
        curated: tuple[int, dict[int, list[str]]] | None = (
            _curated_pool_for_lexicon(
                {"language": language_code, "frequency_list": list_config}
            )
        )
        try:
            _, date_ranges, rates, sds = compute_rate_history(
                selection,
                frequency_list,
                records,
                n_strata=curated[0] if curated else DEFAULT_N_STRATA,
                curated_words_by_stratum=curated[1] if curated else None,
            )
        except NotImplementedError:
            continue
        if not date_ranges:
            continue
        result.append(
            LanguageHistory(
                language=language.get_code(),
                points=_grid_points(date_ranges, rates, sds, interval),
            )
        )
    return result


@app.put(
    "/api/v1/me/lexicons/{lexicon_id}/main",
    status_code=status.HTTP_204_NO_CONTENT,
)
def set_lexicon_main(
    lexicon_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> None:
    """Make this lexicon the main one for its language (its rate = level)."""
    _lexicon_config_or_404(user_id, lexicon_id)
    postgres.set_main_lexicon(user_id, lexicon_id)


@app.delete(
    "/api/v1/me/lexicons/{lexicon_id}/main",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_lexicon_main(
    lexicon_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> None:
    """Clear this lexicon's main flag; its language then has no main."""
    _lexicon_config_or_404(user_id, lexicon_id)
    postgres.clear_main_lexicon(user_id, lexicon_id)


# Self-reported language knowledge: a user's own proficiency estimates,
# entered by hand — distinct from a lexicon's computed rate. Each estimate
# names a curated "kind" first (native speaker, self-assessed, teacher-
# assessed, or a specific certifying organization), which determines the
# scale its value is drawn from; see `emmio.language_knowledge` for the
# taxonomy, the single source of truth both this API and the web picker
# read from.


class KnowledgeValueOption(BaseModel):
    """One selectable value on a knowledge kind's scale."""

    code: str
    label: str


class NumericRangeOption(BaseModel):
    """A continuous numeric scale, sampled at fixed steps (e.g. IELTS)."""

    minimum: float
    maximum: float
    step: float


class KnowledgeKindOption(BaseModel):
    """One assessment kind, with the scale its value must come from."""

    code: str
    label: str
    languages: list[str] | None
    """Language codes this kind applies to, or `None` for any language."""

    values: list[KnowledgeValueOption]
    """Valid discrete values; empty if `numeric_range` is set instead."""

    numeric_range: NumericRangeOption | None
    """Valid continuous range; `None` if `values` is set instead (or the
    kind, like `native`, has no value scale at all)."""

    allows_other: bool
    """Whether a value outside `values` may be entered as free text — an
    "Other" escape hatch next to `values`, or (with `values` empty and no
    `numeric_range`) the whole value field is free text."""

    has_caption: bool
    """Whether this kind needs a free-text caption naming it more
    precisely (e.g. `standardized_test`, which test)."""

    requires_date: bool
    """Whether this kind needs a self-reported date (false only for
    `native`)."""


def _knowledge_kind_option(kind: KnowledgeKind) -> KnowledgeKindOption:
    return KnowledgeKindOption(
        code=kind.code,
        label=kind.label,
        languages=list(kind.languages) if kind.languages is not None else None,
        values=[
            KnowledgeValueOption(code=value.code, label=value.label)
            for value in kind.values
        ],
        numeric_range=(
            NumericRangeOption(
                minimum=kind.numeric_range.minimum,
                maximum=kind.numeric_range.maximum,
                step=kind.numeric_range.step,
            )
            if kind.numeric_range is not None
            else None
        ),
        allows_other=kind.allows_other,
        has_caption=kind.has_caption,
        requires_date=kind.requires_date,
    )


@app.get(
    "/api/v1/language-knowledge-kinds", dependencies=[Depends(get_current_user)]
)
def get_language_knowledge_kinds() -> list[KnowledgeKindOption]:
    """List the curated assessment kinds a proficiency estimate may use."""
    return [_knowledge_kind_option(kind) for kind in KNOWLEDGE_KINDS]


# A field literally named `date` (as the API's JSON key must be) with a
# default value shadows the bare `date` type name in its own annotation:
# class bodies bind the assigned value before evaluating the annotation, so
# `date: date | None = None` would resolve `date | None` against the
# just-bound `None` rather than the imported type, and raise at
# class-definition time. `_OptionalDate` sidesteps the collision.
_OptionalDate = date | None


class LanguageKnowledgeRecord(BaseModel):
    """One self-reported proficiency estimate."""

    id: int
    language: str
    kind: str
    value: str | None
    caption: str | None
    date: _OptionalDate


@app.get("/api/v1/me/language-knowledge")
def get_my_language_knowledge(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[LanguageKnowledgeRecord]:
    """List the authenticated user's proficiency estimates.

    Every estimate ever added is returned — full history, not just the
    latest per language — ordered by language, then newest date first.
    """
    return [
        LanguageKnowledgeRecord(
            id=record_id,
            language=language,
            kind=kind,
            value=value,
            caption=caption,
            date=date_,
        )
        for record_id, language, kind, value, caption, date_ in (
            postgres.get_language_knowledge_records(user_id)
        )
    ]


class CreateLanguageKnowledgeRequest(BaseModel):
    """Payload to add one proficiency estimate."""

    language: str
    kind: str
    value: str | None = None
    caption: str | None = None
    date: _OptionalDate = None


@app.post("/api/v1/me/language-knowledge", status_code=status.HTTP_201_CREATED)
def create_language_knowledge_record(
    request: CreateLanguageKnowledgeRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> LanguageKnowledgeRecord:
    """Add a proficiency estimate for a language.

    Adding never touches earlier estimates for the same language — the
    full self-reported history is kept.
    """
    if not _is_known_language(request.language):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown language `{request.language}`.",
        )
    kind: KnowledgeKind | None = KNOWLEDGE_KINDS_BY_CODE.get(request.kind)
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown assessment kind `{request.kind}`.",
        )
    if kind.languages is not None and request.language not in kind.languages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"`{kind.label}` does not apply to language "
                f"`{request.language}`."
            ),
        )
    if not is_valid_knowledge_value(kind, request.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid value `{request.value}` for `{kind.label}`.",
        )
    if not is_valid_caption(kind, request.caption):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid caption `{request.caption}` for `{kind.label}`.",
        )
    if not is_valid_knowledge_date(kind, request.date):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date `{request.date}` for `{kind.label}`.",
        )
    record_id: int = postgres.add_language_knowledge_record(
        user_id,
        request.language,
        request.kind,
        request.value,
        request.caption,
        request.date,
    )
    return LanguageKnowledgeRecord(
        id=record_id,
        language=request.language,
        kind=request.kind,
        value=request.value,
        caption=request.caption,
        date=request.date,
    )


@app.delete(
    "/api/v1/me/language-knowledge/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_language_knowledge_record(
    record_id: int, user_id: Annotated[str, Depends(get_current_user)]
) -> None:
    """Delete one proficiency estimate."""
    if not postgres.delete_language_knowledge_record(user_id, record_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown language knowledge record `{record_id}`.",
        )


# Curation: reviewing a curated panel's words, the web equivalent of `emmio
# curate` — plus the lighter-weight "not to check" vote an ordinary lexicon
# check answer may also carry (see `AnswerRequest.category`/
# `_record_not_to_check_vote` above; both write into the same
# `curated_words`/`curated_word_records`, curation being a property of the
# list, not of how a curator happened to reach a given word). No session
# concept here, unlike lexicon checking: `get_next_curation_candidate` is a
# cheap query with no expensive per-learner selector state to cache.

# All valid `curated_words.category` codes, for validating `/answer`: `W`
# (real word, group 1, "to check") plus every group-2 "not to check" reason,
# plus `U` (unsure — a curator declining to decide, distinct from silence).
_CURATION_CATEGORY_CODES: frozenset[str] = frozenset(
    {"W", "U", *NOT_TO_CHECK_CATEGORY_CODES.values()}
)

# Curator-facing labels for every code, in menu order — the CLI's
# `CURATION_CATEGORIES` (`emmio/run.py`), reshaped for the web: group 1
# first, then group 2 in the same order `NOT_TO_CHECK_CATEGORIES` defines,
# then "Unsure".
_CURATION_CATEGORY_LABELS: list[tuple[str, str]] = [
    ("W", "Real word"),
    *((code, label) for label, code in NOT_TO_CHECK_CATEGORY_CODES.items()),
    ("U", "Unsure"),
]


class CuratedListSummary(BaseModel):
    """One curated list, for the picker page.

    Addressed by `(language, frequency_list_id)` everywhere in this API —
    the same pair `emmio curate <language> <frequency_list_id>` takes, and
    the schema's actual `UNIQUE (language, frequency_list_id)` key.
    `curated_lists.id` (a `SERIAL`) is a database-internal implementation
    detail and is never exposed here.
    """

    language: str
    frequency_list_id: str
    name: str
    n_strata: int
    words: int  # Total panel words.
    uncurated: int  # Panel words no curator has voted on yet.


@app.get("/api/v1/curation/lists")
def get_curation_lists(
    _user_id: Annotated[str, Depends(get_current_user)],
) -> list[CuratedListSummary]:
    """List every curated list, with its not-curated-by-anyone count."""
    return [
        CuratedListSummary(
            language=language,
            frequency_list_id=frequency_list_id,
            name=name,
            n_strata=n_strata,
            words=postgres.count_curated_words(list_id),
            uncurated=postgres.count_uncurated_words(list_id),
        )
        for list_id, language, frequency_list_id, name, n_strata in (
            postgres.get_curated_lists()
        )
    ]


@app.delete(
    "/api/v1/curation/{language}/{frequency_list_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_curated_list(
    language: str,
    frequency_list_id: str,
    _user_id: Annotated[str, Depends(get_current_user)],
) -> None:
    """Delete a curated list and all its words and vote history.

    Irreversible. Any lexicon backed by this list falls back to the plain
    (uncurated) stratified selector, rather than breaking (see
    `_curated_pool_for_lexicon`).
    """
    list_id: int = _curated_list_id_or_404(language, frequency_list_id)
    postgres.delete_curated_list(list_id)


class CurationCategoryNode(BaseModel):
    """One entry in the category picker, possibly with nested children.

    `code` is `None` for a non-selectable heading — currently just "Not to
    check", grouping the group-(2) reasons together — every other node is
    a real, independently selectable `curated_words.category` code, even
    one with children of its own (e.g. `Misspelling` itself is a valid
    choice, not just its `Missing spaces`/`Missing diacritics` children).
    """

    code: str | None
    label: str
    children: list["CurationCategoryNode"] = []


def _curation_category_node(node: CategoryNode) -> CurationCategoryNode:
    return CurationCategoryNode(
        code=node.code,
        label=node.label,
        children=[_curation_category_node(child) for child in node.children],
    )


@app.get("/api/v1/curation/categories")
def get_curation_categories(
    _user_id: Annotated[str, Depends(get_current_user)],
) -> list[CurationCategoryNode]:
    """Get the category picker tree: group (1), group (2), then "Unsure".

    Group (2) (`NOT_TO_CHECK_TREE`) nests under a non-selectable "Not to
    check" heading — the client renders this as a hierarchical
    radio-button list rather than hardcoding the taxonomy, so the tree
    only has to change in one place (`emmio/lexicon/core.py`) to show up
    here too.
    """
    return [
        CurationCategoryNode(code="W", label="Real word", children=[]),
        CurationCategoryNode(
            code=None,
            label="Not to check",
            children=[
                _curation_category_node(node) for node in NOT_TO_CHECK_TREE
            ],
        ),
        CurationCategoryNode(code="U", label="Unsure", children=[]),
    ]


def _curated_list_id_or_404(language: str, frequency_list_id: str) -> int:
    """Resolve `(language, frequency_list_id)` to the internal numeric id."""
    list_id = postgres.get_curated_list_id(language, frequency_list_id)
    if list_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown curated list `{language}/{frequency_list_id}`.",
        )
    return list_id


def _curation_dictionaries(language: str) -> list[dict]:
    """Get the one dictionary curation always uses: Kaikki, matching the CLI."""
    return [
        {
            "id": "kaikki",
            "from_language": language,
            "name": Language.from_code(language).get_name(),
        }
    ]


def _curation_sentences(language: str) -> list[dict]:
    """Get the one sentence source curation uses: Tatoeba, if cached."""
    return [{"id": "tatoeba", "language": language}]


# Curator judgments a single request may resolve automatically before
# either finding one needing a human or giving up — same reasoning as
# `_DRAW_BUDGET`: caps the work (and the risk of a slow response) a long
# run of already-resolved-but-unvoted panel words could otherwise cause.
_CURATION_SKIP_BUDGET: int = 256


class CurationWordCard(BaseModel):
    """One panel word awaiting this curator's vote, or none left."""

    word: str | None
    stratum: int | None
    auto_resolved: int
    """Panel words this request skipped automatically before finding (or
    failing to find) one needing a human — purely informational, e.g. for
    a "skipped N auto-resolved words" status line; nothing is written for
    them (see `classify_automatically`)."""


@app.get("/api/v1/curation/{language}/{frequency_list_id}/next")
async def get_next_curation_word(
    language: str,
    frequency_list_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    stratum: int | None = None,
) -> CurationWordCard:
    """Get the next panel word needing this curator's vote.

    Mirrors `emmio curate` exactly: words an automatic check already
    resolves are skipped without writing anything, leaving only genuinely
    undecidable words for the human (see `classify_automatically`).
    """
    curated_list_id: int = _curated_list_id_or_404(language, frequency_list_id)
    word_language: Language = Language.from_code(language)
    alphabet: str | None = word_language.get_symbols()
    non_proper_nouns: frozenset[str] = NON_PROPER_NOUNS.get(
        language, frozenset()
    )
    frequency_list: FrequencyList | None = get_data().get_frequency_list(
        parse_frequency_list_identifier(frequency_list_id, language)
    )
    dictionaries: DictionaryCollection = get_data().get_dictionaries(
        [
            DictionaryUsageConfig(
                id="kaikki",
                from_language=language,
                name=word_language.get_name(),
            )
        ]
    )

    skipped: set[str] = set()
    auto_resolved: int = 0
    for _ in range(_CURATION_SKIP_BUDGET):
        word: str | None = postgres.get_next_curation_candidate(
            curated_list_id, user_id, stratum, exclude=skipped
        )
        if word is None:
            break
        if (
            await classify_automatically(
                word,
                word_language,
                alphabet,
                frequency_list,
                non_proper_nouns,
                dictionaries,
            )
            is not None
        ):
            skipped.add(word)
            auto_resolved += 1
            continue
        return CurationWordCard(
            word=word,
            stratum=postgres.get_curated_word_stratum(curated_list_id, word),
            auto_resolved=auto_resolved,
        )
    return CurationWordCard(
        word=None, stratum=None, auto_resolved=auto_resolved
    )


class CuratedWordEntry(BaseModel):
    """One word in a curated list, with its current curation status."""

    word: str
    stratum: int
    category: str  # A `curated_words.category` code, e.g. `W` or `U`.
    category_label: str  # `category`, spelled out.
    votes: int
    agreement: float | None


class CuratedWordsPage(BaseModel):
    """One page of a curated list's words, for the review table."""

    words: list[CuratedWordEntry]
    total: int  # Total words matching `stratum`, across every page.
    page: int
    page_size: int


@app.get("/api/v1/curation/{language}/{frequency_list_id}/words")
def get_curation_words(
    language: str,
    frequency_list_id: str,
    _user_id: Annotated[str, Depends(get_current_user)],
    page: int = 1,
    page_size: int = _WORDS_PAGE_SIZE_DEFAULT,
    stratum: int | None = None,
) -> CuratedWordsPage:
    """Get one page of a curated list's words, with their curation status.

    Ordered the same way the list is served (`stratum`, then `panel_order`
    within it) — a stable reading order across pages, not just whatever
    order the database happens to return rows in. `page`/`page_size` are
    clamped rather than rejected, matching `/me/lexicons/{id}/next`'s
    `count` handling.
    """
    curated_list_id: int = _curated_list_id_or_404(language, frequency_list_id)
    page = max(1, page)
    page_size = max(1, min(page_size, _WORDS_PAGE_SIZE_MAX))
    offset: int = (page - 1) * page_size

    labels: dict[str, str] = dict(_CURATION_CATEGORY_LABELS)
    rows = postgres.get_curated_words(
        curated_list_id, stratum, offset=offset, limit=page_size
    )
    return CuratedWordsPage(
        words=[
            CuratedWordEntry(
                word=word,
                stratum=word_stratum,
                category=category,
                category_label=labels.get(category, category),
                votes=votes,
                agreement=agreement,
            )
            for (
                word,
                word_stratum,
                _panel_order,
                category,
                votes,
                agreement,
            ) in rows
        ],
        total=postgres.count_curated_words(curated_list_id, stratum),
        page=page,
        page_size=page_size,
    )


@app.get("/api/v1/curation/{language}/{frequency_list_id}/translation")
async def get_curation_translation(
    language: str,
    frequency_list_id: str,
    word: str,
    _user_id: Annotated[str, Depends(get_current_user)],
) -> Translation:
    """Get a word's Kaikki translation — the curator's evidence, not a quiz."""
    _curated_list_id_or_404(language, frequency_list_id)
    return Translation(
        word=word,
        dictionaries=await _translate(
            word, language, _curation_dictionaries(language)
        ),
    )


@app.get("/api/v1/curation/{language}/{frequency_list_id}/sentence")
def get_curation_sentence(
    language: str,
    frequency_list_id: str,
    word: str,
    _user_id: Annotated[str, Depends(get_current_user)],
) -> Sentence:
    """Get one Tatoeba example sentence for a word (slow, kept off `/next`)."""
    _curated_list_id_or_404(language, frequency_list_id)
    return Sentence(
        word=word,
        sentence=_sentence_html(word, language, _curation_sentences(language)),
    )


class CurationAnswerRequest(BaseModel):
    """A curator's category vote for one word."""

    word: str
    category: str  # A `curated_words.category` code, e.g. `W` or `P`.


@app.post(
    "/api/v1/curation/{language}/{frequency_list_id}/answer",
    status_code=status.HTTP_204_NO_CONTENT,
)
def answer_curation_word(
    language: str,
    frequency_list_id: str,
    request: CurationAnswerRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> None:
    """Record a curator's vote for one panel word.

    Every vote is kept (`curated_word_records`); the consensus cached on
    `curated_words` is the mode of each curator's *latest* vote (see
    `postgres.record_curation_vote`) — re-voting updates, never
    duplicates.
    """
    curated_list_id: int = _curated_list_id_or_404(language, frequency_list_id)
    if request.category not in _CURATION_CATEGORY_CODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid category `{request.category}`.",
        )
    try:
        postgres.record_curation_vote(
            curated_list_id, request.word, request.category, user_id
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error


# Words classified and voted on per call, so a large list is auto-curated
# incrementally (the client calls again for more) rather than risking one
# huge blocking request — same reasoning as `_CURATION_SKIP_BUDGET`.
_AUTO_CURATE_BUDGET: int = 256


class AutoCurateResult(BaseModel):
    """Outcome of one auto-curation pass."""

    resolved: int  # Words classified and voted on this call.
    checked: int  # Words examined this call (resolved + left undecidable).
    remaining: int
    """Panel words the "Emmio" curator still has no vote for, after this
    call. Does not necessarily shrink to 0 by repeating the call: a word
    with no automatic evidence either way stays undecidable forever (that
    is the entire point — it is left for a human), so `remaining` can
    plateau above 0 once every resolvable word is done.
    """


@app.post("/api/v1/curation/{language}/{frequency_list_id}/auto-curate")
async def auto_curate_words(
    language: str,
    frequency_list_id: str,
    _user_id: Annotated[str, Depends(get_current_user)],
) -> AutoCurateResult:
    """Auto-curate up to `_AUTO_CURATE_BUDGET` words, voting as "Emmio".

    Uses exactly the evidence `emmio curate`/`/next` already use to
    silently *skip* a word without writing anything (see
    `classify_automatically`) — the difference here is that a real vote
    gets recorded, attributed to the synthetic "Emmio" curator
    (`EMMIO_CURATOR_USER_ID`) rather than recomputed fresh every time.
    That curator is created on first use (`postgres.ensure_user`, with no
    password, so nothing can log in as it) and votes exactly like any
    other curator: a human voting on the same word later is simply
    another `curator_id`, and the usual "mode of each curator's latest
    vote" consensus lets that human override the bot with no special
    mechanism needed.

    Only words "Emmio" has not already voted on are considered
    (`get_curator_unvoted_words`, the same call `--from-lexicon-history`
    uses for a human curator), in panel order, so repeated calls make
    steady forward progress instead of re-examining an arbitrary subset
    each time.
    """
    curated_list_id: int = _curated_list_id_or_404(language, frequency_list_id)
    postgres.ensure_user(EMMIO_CURATOR_USER_ID, EMMIO_CURATOR_NAME)

    word_language: Language = Language.from_code(language)
    alphabet: str | None = word_language.get_symbols()
    non_proper_nouns: frozenset[str] = NON_PROPER_NOUNS.get(
        language, frozenset()
    )
    frequency_list: FrequencyList | None = get_data().get_frequency_list(
        parse_frequency_list_identifier(frequency_list_id, language)
    )
    dictionaries: DictionaryCollection = get_data().get_dictionaries(
        [
            DictionaryUsageConfig(
                id="kaikki",
                from_language=language,
                name=word_language.get_name(),
            )
        ]
    )

    unvoted: set[str] = postgres.get_curator_unvoted_words(
        curated_list_id, EMMIO_CURATOR_USER_ID
    )
    ordered_words: list[str] = [
        word
        for word, *_ in postgres.get_curated_words(curated_list_id)
        if word in unvoted
    ]

    resolved: int = 0
    checked: int = 0
    for word in ordered_words[:_AUTO_CURATE_BUDGET]:
        checked += 1
        category: str | None = await classify_automatically(
            word,
            word_language,
            alphabet,
            frequency_list,
            non_proper_nouns,
            dictionaries,
        )
        if category is None:
            continue
        postgres.record_curation_vote(
            curated_list_id, word, category, EMMIO_CURATOR_USER_ID
        )
        resolved += 1

    return AutoCurateResult(
        resolved=resolved, checked=checked, remaining=len(unvoted) - resolved
    )


# Learning. Only the spaced-repetition review of words already being learned is
# served; adding new words needs the interactive `Teacher` and is not yet here.


def _learning_entry(user_id: str, learning_id: str) -> LearningEntry:
    """Get the user's learning from the per-process cache.

    Replaying every record of a learning on each request does not scale; the
    registry caches the loaded `Learning` and reloads it only when its
    freshness stamp shows records arrived through another path (undo, CLI).
    Use the entry's lock around any access to the instance.
    """
    config: dict = _learning_config_or_404(user_id, learning_id)
    return LEARNING_REGISTRY.entry(user_id, learning_id, config)


class LearningStats(BaseModel):
    """Details and statistics for a single learning."""

    learning_id: str
    name: str
    learning_language: str
    learning: int  # Words currently being learned.
    to_repeat: int  # Words due for repetition now.
    to_add: int  # New words still allowed today.
    added_today: int  # New words added today.
    answers: int  # Total answers recorded.
    actions: int  # Meaningful actions (right/wrong answers).


@app.get("/api/v1/me/learnings/{learning_id}/stats")
def get_learning_stats(
    learning_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> LearningStats:
    """Get details and statistics for one learning.

    Loads the learning's records to compute the repetition schedule, so it is
    heavier than the list endpoint; intended for a single-learning view.
    """
    entry: LearningEntry = _learning_entry(user_id, learning_id)
    with entry.lock:
        learning: Learning = entry.learning
        return LearningStats(
            learning_id=learning_id,
            name=learning.config.name,
            learning_language=learning.learning_language.get_code(),
            learning=learning.count_questions_to_learn(),
            to_repeat=learning.count_questions_to_repeat(),
            to_add=learning.count_questions_to_add(),
            added_today=learning.count_questions_added_today(),
            answers=len(learning.get_records()),
            actions=learning.get_actions(),
        )


@app.get("/api/v1/me/learnings/{learning_id}/next")
def get_next_questions(
    learning_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    count: int = 1,
    exclude: Annotated[list[str] | None, Query()] = None,
) -> NextWords:
    """Get the next words due for repetition, soonest-due first.

    `count` lets the client prefetch a queue; `exclude` lists words already
    queued so the batch has no duplicates.
    """
    entry: LearningEntry = _learning_entry(user_id, learning_id)
    with entry.lock:
        language_object: Language = entry.learning.learning_language
        questions: list[str] = entry.learning.get_next_questions(
            max(1, min(count, _BATCH_MAX)), set(exclude or [])
        )
    answers = postgres.get_last_learn_answers(user_id, learning_id, questions)
    return NextWords(
        language=language_object.get_code(),
        words=_word_cards(
            questions,
            answers,
            _LEARN_RESPONSE_LABELS,
            typed_language=language_object,
        ),
    )


# Question-type codes stored in `learn_records.extra.qt`. A record without `qt`
# predates this provenance and so has an unknown question type.
QUESTION_TYPE_KNOW: str = "know"  # See the word, self-assess, reveal meaning.
QUESTION_TYPE_CHOICE: str = "choice"  # Pick the translation among several.
QUESTION_TYPE_CONNECT: str = "connect"  # Match several words to translations.
QUESTION_TYPE_TYPE_WORD: str = "type_word"  # See the meaning, type the word.

# Single-word question types from easiest (recognition) to hardest (production).
# The chosen type rises with the word's run of correct answers, so a word is
# recognized before it must be produced.
_SINGLE_QUESTION_TYPES: tuple[str, ...] = (
    QUESTION_TYPE_KNOW,
    QUESTION_TYPE_CHOICE,
    QUESTION_TYPE_TYPE_WORD,
)
# Correct-answer streak a word needs before a single-word type may be asked.
_QUESTION_TYPE_MIN_STREAK: dict[str, int] = {
    QUESTION_TYPE_KNOW: 0,
    QUESTION_TYPE_CHOICE: 1,
    QUESTION_TYPE_TYPE_WORD: 2,
}
_ALL_QUESTION_TYPES: tuple[str, ...] = (
    QUESTION_TYPE_KNOW,
    QUESTION_TYPE_CHOICE,
    QUESTION_TYPE_CONNECT,
    QUESTION_TYPE_TYPE_WORD,
)
# Human-readable labels, matching the headings the learn page shows for each.
_QUESTION_TYPE_LABELS: dict[str, str] = {
    QUESTION_TYPE_KNOW: "Know / don't know",
    QUESTION_TYPE_CHOICE: "Choose the translation",
    QUESTION_TYPE_CONNECT: "Connect the words",
    QUESTION_TYPE_TYPE_WORD: "Type the word",
}


class QuestionTypeOption(BaseModel):
    """A question type a learning can be restricted to."""

    value: str  # Stored in `scheme.question_types`, e.g. `type_word`.
    label: str  # Human-readable name shown in the UI.


@app.get("/api/v1/question-types", dependencies=[Depends(get_current_user)])
def get_question_types() -> list[QuestionTypeOption]:
    """List the question types a learning can be restricted to.

    A learning with no `question_types` configured allows all of them.
    """
    return [
        QuestionTypeOption(value=value, label=_QUESTION_TYPE_LABELS[value])
        for value in _ALL_QUESTION_TYPES
    ]


# Multiple-choice and connect sizes.
_CHOICE_OPTIONS: int = 4
_CONNECT_SIZE: int = 4
# Due words to consider when forming one question.
_QUESTION_BATCH: int = 12
# A word not answered for this long falls back to `know` regardless of its
# streak: after such a gap the streak no longer proves the word is retained.
_STALE_AFTER: timedelta = timedelta(weeks=2)


class LearningAnswerRequest(BaseModel):
    """A user's answer to a repetition question."""

    word: str
    response: str  # A `Response` value: "y" right, "n" wrong, "s" skip.
    question_type: str = QUESTION_TYPE_TYPE_WORD
    """How the word was asked, stored as provenance (`extra.qt`).

    A record with no `qt` predates this and is treated as an unknown type.
    """
    sentence_id: int | None = None  # The example shown (`extra.si`), if any.
    session_id: str | None = None
    """Open learning session to count the answer into, if the client has one.

    The answer is persisted either way; the identifier only groups answers
    into a `learn_sessions` row.
    """
    seconds: float | None = None
    """How long the question was on screen, used to set `request_time`.

    Measured client-side as a duration (robust to clock skew); the server stores
    `request_time = response_time - seconds`.
    """


@app.post(
    "/api/v1/me/learnings/{learning_id}/answer",
    status_code=status.HTTP_204_NO_CONTENT,
)
def answer_question(
    learning_id: str,
    request: LearningAnswerRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> None:
    """Record an answer to a repetition question.

    The question type (`qt`), the example sentence shown (`si`), and how long
    the card was on screen (as `request_time`) are kept as provenance, so a
    record stays interpretable as more question types are added. The answer
    goes through the cached `Learning` instance, so the repetition schedule
    updates in place; with a `session_id` it also counts into the open
    learning session's `learn_sessions` row.
    """
    try:
        response: Response = Response(request.response)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid response `{request.response}`.",
        ) from error
    now: datetime = datetime.now(UTC)
    request_time: datetime | None = (
        now - timedelta(seconds=request.seconds)
        if request.seconds is not None
        else None
    )
    entry: LearningEntry = _learning_entry(user_id, learning_id)
    with entry.lock:
        entry.learning.register(
            response,
            request.sentence_id or 0,
            request.word,
            time=now,
            request_time=request_time,
            question_type=request.question_type,
        )
        entry.learning.write()
        entry.stamp += 1
        if (
            entry.session is not None
            and request.session_id == entry.session.session_id
        ):
            entry.session.actions += 1
            entry.session.last_action = now


class OpenLearningSessionRequest(BaseModel):
    """Payload to open a learning session."""

    type: str = "repeat_and_learn_new"
    """Session type stored in the log (mirrors the CLI teacher's types)."""


@app.post(
    "/api/v1/me/learnings/{learning_id}/sessions",
    status_code=status.HTTP_201_CREATED,
)
def open_learning_session(
    learning_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    request: OpenLearningSessionRequest | None = None,
) -> OpenedSession:
    """Open a learning session on the learning.

    Answers carrying the returned identifier are grouped into one
    `learn_sessions` row (start, end, action count) when the session closes —
    the same bookkeeping the CLI teacher does. Opening also warms the cached
    learning, so the first question arrives without replaying the records.
    """
    config: dict = _learning_config_or_404(user_id, learning_id)
    session = LEARNING_REGISTRY.open_session(
        user_id,
        learning_id,
        config,
        request.type if request is not None else "repeat_and_learn_new",
    )
    return OpenedSession(session_id=session.session_id)


@app.post(
    "/api/v1/me/learnings/{learning_id}/sessions/{session_id}/close",
    status_code=status.HTTP_204_NO_CONTENT,
)
def close_learning_session(
    learning_id: str,
    session_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> None:
    """Close the learning session, writing its log row.

    Idempotent: closing an unknown or already-closed session is a no-op, so
    client retries are safe. A session that is never closed is finalized when
    it expires or the server shuts down; a session without answers leaves no
    row.
    """
    _learning_config_or_404(user_id, learning_id)
    LEARNING_REGISTRY.close_session(user_id, learning_id, session_id)


class ConnectPair(BaseModel):
    """One word and its short translation, for a connect (matching) question."""

    word: str
    translation: str


class Question(BaseModel):
    """A review question of one of several types.

    Only the fields a given `type` needs are set. `type` is `None` when no
    review question is currently due. The client grades the answer against the
    provided data (the server's role is to supply the question and its key),
    then records each covered word via `/answer` with this `type`.
    """

    type: str | None
    language: str
    words: list[str] = []  # The word(s) the question covers (for `/answer`).
    accepted: list[str] | None = None  # `type_word`: answers that count right.
    options: list[str] | None = None  # `choice`: the translations to pick from.
    answer: str | None = None  # `choice`: the correct option.
    pairs: list[ConnectPair] | None = None  # `connect`: words and translations.
    streak: int | None = None
    """The word's run of correct answers, for single-word questions."""
    last_answer_time: datetime | None = None
    """When the word was last answered, for single-word questions."""


def _streak(learning: Learning, word: str) -> int:
    """Get the word's run of correct answers (0 if new or last was wrong)."""
    knowledge = learning.get_knowledge(word)
    return knowledge.count_right_streak() if knowledge else 0


def _last_answer_time(learning: Learning, word: str) -> datetime | None:
    """Get when the word was last answered (postpones don't count)."""
    knowledge = learning.get_knowledge(word)
    return knowledge.get_last_answer_time() if knowledge else None


def _single_question_type(
    streak: int, enabled: set[str], *, choice_feasible: bool, stale: bool
) -> str:
    """Pick a single-word question type for a word by its knowledge.

    The hardest enabled, feasible type the word has earned by its streak; if it
    has earned none, the easiest enabled, feasible type. `type_word` is always
    feasible, so a type is always returned. A stale word (not answered for
    `_STALE_AFTER`) gets `know` regardless of its streak, when enabled.
    """

    def feasible(question_type: str) -> bool:
        if question_type not in enabled:
            return False
        if question_type == QUESTION_TYPE_CHOICE:
            return choice_feasible
        return True  # `know` and `type_word` need no extra data.

    if stale and feasible(QUESTION_TYPE_KNOW):
        return QUESTION_TYPE_KNOW

    earned: list[str] = [
        question_type
        for question_type in _SINGLE_QUESTION_TYPES
        if feasible(question_type)
        and streak >= _QUESTION_TYPE_MIN_STREAK[question_type]
    ]
    if earned:
        return earned[-1]  # Hardest earned (the tuple is easiest-first).
    feasible_types: list[str] = [
        question_type
        for question_type in _SINGLE_QUESTION_TYPES
        if feasible(question_type)
    ]
    return feasible_types[0] if feasible_types else QUESTION_TYPE_TYPE_WORD


@app.get("/api/v1/me/learnings/{learning_id}/question")
async def get_question(
    learning_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    exclude: Annotated[list[str] | None, Query()] = None,
) -> Question:
    """Get the next due review question, of a type chosen for the words.

    The type is decided by the learning's configured `question_types`, by each
    word's knowledge (recognition before production), and by what data exists
    (a short translation is needed for `choice`/`connect`). A word not answered
    for `_STALE_AFTER` falls back to `know`. New words are not served here —
    they come from `/new`. `type` is `None` when nothing is due.
    """
    entry: LearningEntry = _learning_entry(user_id, learning_id)
    with entry.lock:
        learning: Learning = entry.learning
        language: str = learning.learning_language.get_code()
        due: list[str] = learning.get_next_questions(
            _QUESTION_BATCH, set(exclude or [])
        )
        # Snapshot the streaks and last answer times under the lock: the
        # translation lookups below await, and the instance may take answers
        # meanwhile.
        streaks: dict[str, int] = {
            word: _streak(learning, word) for word in due
        }
        last_answered: dict[str, datetime | None] = {
            word: _last_answer_time(learning, word) for word in due
        }
    now: datetime = datetime.now(UTC)
    stale: dict[str, bool] = {
        word: time is not None and now - time > _STALE_AFTER
        for word, time in last_answered.items()
    }
    if not due:
        return Question(type=None, language=language)

    scheme = learning.config.scheme
    configured: list[str] | None = (
        scheme.question_types if scheme is not None else None
    )
    enabled: set[str] = set(configured or _ALL_QUESTION_TYPES)

    # Short translations for the due words (deduplicated by translation so
    # options and matches are unambiguous), used by `choice` and `connect` — so
    # only looked up when one of those types is enabled.
    translatable: dict[str, str] = {}
    seen_translations: set[str] = set()
    if enabled & {QUESTION_TYPE_CHOICE, QUESTION_TYPE_CONNECT}:
        dictionaries: DictionaryCollection = get_data().get_dictionaries(
            learning.config.dictionaries
        )
        language_object: Language = learning.learning_language
        base_languages: list[Language] = learning.base_languages
        for word in due:
            translation: str | None = await _short_translation(
                word, language_object, dictionaries, base_languages
            )
            if translation is not None and translation not in seen_translations:
                translatable[word] = translation
                seen_translations.add(translation)

    # Connect: when enough low-knowledge due words can be matched, group them.
    # Stale words are left out: they should get `know` on the single-word path.
    if QUESTION_TYPE_CONNECT in enabled:
        matchable: list[str] = [
            word
            for word in due
            if word in translatable and streaks[word] <= 1 and not stale[word]
        ]
        if len(matchable) >= _CONNECT_SIZE:
            chosen: list[str] = matchable[:_CONNECT_SIZE]
            return Question(
                type=QUESTION_TYPE_CONNECT,
                language=language,
                words=chosen,
                pairs=[
                    ConnectPair(word=word, translation=translatable[word])
                    for word in chosen
                ],
            )

    word = due[0]
    choice_feasible: bool = (
        word in translatable and len(seen_translations) >= _CHOICE_OPTIONS
    )
    question_type: str = _single_question_type(
        streaks[word],
        enabled,
        choice_feasible=choice_feasible,
        stale=stale[word],
    )
    if question_type == QUESTION_TYPE_CHOICE:
        correct: str = translatable[word]
        distractors: list[str] = random.sample(
            sorted(seen_translations - {correct}), _CHOICE_OPTIONS - 1
        )
        options: list[str] = [correct, *distractors]
        random.shuffle(options)
        return Question(
            type=QUESTION_TYPE_CHOICE,
            language=language,
            words=[word],
            options=options,
            answer=correct,
            streak=streaks[word],
            last_answer_time=last_answered[word],
        )
    if question_type == QUESTION_TYPE_KNOW:
        return Question(
            type=QUESTION_TYPE_KNOW,
            language=language,
            words=[word],
            streak=streaks[word],
            last_answer_time=last_answered[word],
        )
    return Question(
        type=QUESTION_TYPE_TYPE_WORD,
        language=language,
        words=[word],
        accepted=_accepted_forms(word, learning.learning_language),
        streak=streaks[word],
        last_answer_time=last_answered[word],
    )


@app.post("/api/v1/me/learnings/{learning_id}/undo")
def undo_learning_answer(
    learning_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> NextWord:
    """Undo the most recent answer in the learning, returning its word.

    Lets a mis-clicked repetition answer be corrected by re-answering.
    """
    _learning_config_or_404(user_id, learning_id)
    word: str | None = postgres.delete_last_learn_record(user_id, learning_id)
    # The delete bypassed the cached instance; drop it so the next request
    # reloads from ground truth.
    LEARNING_REGISTRY.invalidate(user_id, learning_id)
    return NextWord(word=word)


@app.get("/api/v1/me/learnings/{learning_id}/dictionaries")
def get_learning_dictionaries(
    learning_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> list[DictionaryInfo]:
    """List the learning's dictionaries so the client can load each one."""
    config: dict = _learning_config_or_404(user_id, learning_id)
    return _dictionary_infos(config.get("dictionaries"))


@app.get("/api/v1/me/learnings/{learning_id}/translation")
async def get_learning_translation(
    learning_id: str,
    word: str,
    user_id: Annotated[str, Depends(get_current_user)],
    index: int | None = None,
    hide_word: bool = True,  # noqa: FBT001, FBT002
) -> Translation:
    """Get a word's translation from the learning's configured dictionaries.

    With `hide_word` (the default) the word is blanked out of the definitions,
    so the meaning serves as a recall prompt without revealing the answer — used
    by the type-the-word question. The know question passes `hide_word=false`
    to show the full meaning once the user has self-assessed. `index`
    optionally restricts the result to one dictionary (see `/dictionaries`).
    """
    config: dict = _learning_config_or_404(user_id, learning_id)
    return Translation(
        word=word,
        dictionaries=await _translate(
            word,
            config["learning_language"],
            config.get("dictionaries"),
            index=index,
            hide_word=hide_word,
        ),
    )


@app.get("/api/v1/me/learnings/{learning_id}/sentence")
def get_learning_sentence(
    learning_id: str,
    word: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> Sentence:
    """Get one example sentence for a word, blanked, with a translation.

    A recall prompt: the word is blanked out and the sentence comes with one of
    its translations into a base language (only translated sentences are used).
    A slow lookup kept off `/next` so the card appears immediately and the
    example is revealed when it arrives.
    """
    config: dict = _learning_config_or_404(user_id, learning_id)
    result: tuple[int, str, str] | None = _learning_sentence(
        word,
        config["learning_language"],
        config.get("sentences"),
        config.get("base_languages") or [],
    )
    if result is None:
        return Sentence(word=word, sentence=None)
    sentence_id, sentence_html, translation = result
    return Sentence(
        word=word,
        sentence=sentence_html,
        translation=translation,
        sentence_id=sentence_id,
    )


# Media types for the audio file extensions Emmio stores, so browsers get a
# type they can play (Python's `mimetypes` maps `.ogg` to `application/ogg`).
_AUDIO_MEDIA_TYPES: dict[str, str] = {
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
}


@app.get("/api/v1/me/learnings/{learning_id}/audio")
def get_learning_audio(
    learning_id: str,
    word: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> FileResponse:
    """Stream a pronunciation recording for a word in the learning's language.

    Returns the first available recording across the learning's configured audio
    providers, in priority order (local directories first; Wikimedia Commons,
    which downloads on demand, last). Responds 404 when the learning has audio
    playback disabled, no audio configured, or no recording is found.
    """
    config: dict = _learning_config_or_404(user_id, learning_id)
    if not config.get("play_audio", True):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio playback is disabled for this learning.",
        )
    audio_configs: list[dict] | None = config.get("audio")
    if not audio_configs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No audio configured for this learning.",
        )
    collection = get_data().get_audio_collection(
        [AudioUsageConfig(**audio) for audio in audio_configs]
    )
    # Ask providers one at a time and stop at the first hit, so a local file
    # short-circuits the on-demand Wikimedia download of a later provider.
    path: Path | None = None
    with log_duration(f"audio lookup for `{word}` ({learning_id})", logger):
        for provider in collection.audio_providers:
            if paths := provider.get_paths(word):
                path = paths[0]
                break
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No audio for `{word}`.",
        )
    # Transcode Ogg Vorbis (and other formats Safari/iOS cannot play) to MP3,
    # cached, so every browser gets a playable file.
    with log_duration(f"audio transcode for `{word}` ({learning_id})", logger):
        path = to_browser_playable(
            path, get_data().get_audio_data().path / "cache" / "browser"
        )
    return FileResponse(
        path, media_type=_AUDIO_MEDIA_TYPES.get(path.suffix.lower())
    )


class NewQuestion(BaseModel):
    """The next new word to add to a learning, or `None` when none remains."""

    word: str | None
    accepted: list[str] | None = None  # Typed answers that count as correct.
    check_lexicon: str | None = None
    """Lexicon to ask know/don't-know in *before* learning this word.

    Set when the learning has an `ask_lexicon` and the word has not been
    answered there yet: the client first presents a yes/no check and posts
    the answer to that lexicon's `/answer`. "Know" means skip the word
    (request `/new` again); "don't know" admits it to learning. `None` means
    learn the word directly.
    """
    question_type: str | None = None
    """How to present the word's first exposure: `know` when the learning allows
    it (see the word, self-assess, reveal meaning), else `type_word`. Ignored
    when `check_lexicon` already asks know/don't-know first.
    """
    remaining_today: int  # New words still allowed today (`max_for_day`).


# Most dictionary look-ups one `/new` request may perform before giving up.
# New-word selection re-walks the question lists from the top each call (it is
# stateless), skipping already-handled words cheaply in memory; only words at
# the frontier need a slow dictionary "is it common" check. This caps that work
# so a long run of undefined words cannot stall a request (it returns no word,
# and the client may retry).
_NEW_WORD_DICT_BUDGET: int = 64


async def _is_common(
    word: str,
    dictionaries: DictionaryCollection,
    language: Language,
    base_languages: list[Language],
) -> bool:
    """Whether a word is worth learning per the learning's dictionaries.

    Ports `Teacher.check_common`: a word is skipped when no configured
    dictionary defines it, or when it is solely an uncommon form of other words.
    """
    if not await dictionaries.get_items(word, language):
        return False  # No definition anywhere.
    items = await dictionaries.get_items(word, language, follow_links=False)
    for item in items:
        for base_language in base_languages:
            if item.has_definitions() and item.is_not_common(base_language):
                return False  # Solely an uncommon form of another word.
    return True


@app.get("/api/v1/me/learnings/{learning_id}/new")
async def get_new_question_word(
    learning_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    exclude: Annotated[list[str] | None, Query()] = None,
) -> NewQuestion:
    """Get the next new word to add to a learning, from its question lists.

    Ports the selection half of `Teacher`: walks the configured frequency lists
    (or, for a `symbol` learning, the learning language's own alphabet) in order
    and returns the first candidate worth learning, skipping words already
    being learned, already known in a `check_lexicons` lexicon, or not common
    per the configured dictionaries. A word marked "don't know" in a check
    lexicon is returned to learn directly; otherwise, when an `ask_lexicon` is
    configured and the word is new there, it is returned with `check_lexicon`
    set so the client first asks the user know/don't-know.

    Stateless: it re-scans from the top each call (the in-memory skips are
    cheap), so an answered or admitted word simply stops being returned next
    time. Returns `word=None` when the daily limit is reached, the learning
    has no new-question scheme, or the lists are exhausted.
    """
    entry: LearningEntry = _learning_entry(user_id, learning_id)
    with entry.lock:
        learning: Learning = entry.learning
        remaining: int = learning.count_questions_to_add()
    scheme = learning.config.scheme
    learning_type: LearningType = learning.config.learning_type
    if (
        remaining <= 0
        or scheme is None
        or scheme.new_question is None
        or (
            learning_type == LearningType.WORD
            and not scheme.new_question.pick_from
        )
    ):
        return NewQuestion(word=None, remaining_today=max(0, remaining))

    new_question = scheme.new_question
    data = get_data()

    # Candidate words, list-then-rank order (mirrors `Teacher.question_ids`).
    candidates: list[str] = []
    if learning_type == LearningType.SYMBOL:
        candidates.extend(learning.learning_language.symbols)
    else:
        for list_config in new_question.pick_from:
            word_list = data.get_list(list_config)
            if word_list is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=(
                        f"Question list `{list_config.id}` could not be loaded."
                    ),
                )
            candidates.extend(word_list.get_words())

    # Current state for the non-interactive filters, each loaded once.
    check_states: list[dict[str, str | None]] = [
        postgres.get_lexicon_word_states(user_id, lexicon.id)
        for lexicon in (new_question.check_lexicons or [])
    ]
    ask_lexicon_id: str | None = (
        new_question.ask_lexicon.id if new_question.ask_lexicon else None
    )
    ask_states: dict[str, str | None] = (
        postgres.get_lexicon_word_states(user_id, ask_lexicon_id)
        if ask_lexicon_id
        else {}
    )
    dictionaries: DictionaryCollection = (
        data.get_dictionaries(new_question.ignore_not_common)
        if new_question.ignore_not_common
        else DictionaryCollection([])
    )

    language: Language = learning.learning_language
    dont: str = LexiconResponse.DONT.to_code()
    excluded: set[str] = set(exclude or [])
    dict_checks: int = 0

    for word in candidates:
        if word in excluded or learning.has(word):
            continue
        # Already known (anything but "don't know") in a check lexicon -> skip.
        if any(
            word in states and states[word] != dont for states in check_states
        ):
            continue
        if dictionaries.dictionaries:
            dict_checks += 1
            if dict_checks > _NEW_WORD_DICT_BUDGET:
                break  # Budget spent; report no word, the client may retry.
            if not await _is_common(
                word, dictionaries, language, learning.base_languages
            ):
                continue
        # A "don't know" in a check lexicon means learn it now, skipping the
        # ask-lexicon prompt; an unseen word with an `ask_lexicon` is asked
        # first; anything else is learned directly.
        check_lexicon: str | None = None
        if not any(word in states for states in check_states) and (
            ask_lexicon_id is not None and word not in ask_states
        ):
            check_lexicon = ask_lexicon_id
        # First exposure is the gentlest enabled type: a new word cannot be
        # produced from its meaning, so `know` is used unless the learning
        # excludes it.
        enabled_types: set[str] = set(
            scheme.question_types or _ALL_QUESTION_TYPES
        )
        return NewQuestion(
            word=word,
            accepted=_accepted_forms(word, learning.learning_language),
            check_lexicon=check_lexicon,
            question_type=(
                QUESTION_TYPE_KNOW
                if QUESTION_TYPE_KNOW in enabled_types
                else QUESTION_TYPE_TYPE_WORD
            ),
            remaining_today=remaining,
        )

    return NewQuestion(word=None, remaining_today=remaining)


# Serve shared documentation assets (logo, headers) read-only, so the web
# interface can reuse them without duplicating the files into `web/`.
_DOC_DIR: Path = Path(__file__).resolve().parents[2] / "doc"
app.mount("/doc", StaticFiles(directory=_DOC_DIR), name="doc")

# Serve generated design assets (currently just the icon font used by the
# lexicon selection-strategy glyphs) the same read-only way.
_DATA_DIR: Path = Path(__file__).resolve().parents[2] / "data"
app.mount("/data", StaticFiles(directory=_DATA_DIR), name="data")

# Serve the static web interface from the same origin as the API, so the
# browser's `fetch` calls to `/api/v1/...` need no CORS configuration. Mounted
# last so it never shadows an API route.
_WEB_DIR: Path = Path(__file__).resolve().parents[2] / "web"


@app.get("/")
async def root() -> RedirectResponse:
    """Send the site root to the public landing page.

    The landing page itself forwards already-authenticated visitors on to the
    dashboard (it reads the token in the browser), so the server can redirect
    unconditionally here.
    """
    return RedirectResponse(url="/app/landing")


@app.get("/app/{page}")
async def serve_web_page(page: str) -> FileResponse:
    """Serve a web page, resolving extension-less paths to their `.html` file.

    Clean URLs like `/app/profile` map to `profile.html` so the address bar
    hides the extension; real assets such as `base.css` or `app.js` are still
    served as-is. Declared before the `StaticFiles` mount below so it takes
    precedence for single-segment paths under `/app`.
    """
    target: Path = _WEB_DIR / f"{page}.html"
    if not target.is_file():
        target = _WEB_DIR / page
    resolved: Path = target.resolve()
    if not target.is_file() or not resolved.is_relative_to(_WEB_DIR):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(resolved)


app.mount("/app", StaticFiles(directory=_WEB_DIR, html=True), name="web")
