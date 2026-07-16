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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import mkdtemp
from typing import Annotated

import jwt
from colour import Color
from fastapi import (
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.responses import Response as HTTPResponse
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
from emmio.data import Data
from emmio.dictionary.config import DictionaryUsageConfig
from emmio.dictionary.core import DictionaryCollection
from emmio.dictionary.en_wiktionary import kaikki_language_name
from emmio.language import KnownLanguages, Language, LanguageNotFoundError
from emmio.learn.core import Learning, Response
from emmio.lexicon.config import LexiconConfig, LexiconSelection
from emmio.lexicon.core import (
    DEFAULT_N_STRATA,
    RATE_ESTIMATOR_BY_SELECTION,
    AnswerType,
    Lexicon,
    LexiconResponse,
    RateEstimator,
    compute_lexicon_rate,
    estimate_rate_with_sd,
    select_next_word,
    stratum_of_rank,
)
from emmio.lexicon.visualizer import LexiconVisualizer
from emmio.lists.config import ListUsageConfig
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
    name: str | None  # Display name; the identifier is used when not set.
    words: int  # Number of words checked so far.
    dont_last_week: int  # "Don't know" answers in the last 7 days.
    rate: float | None  # Vocabulary rate, or None if not enough data.
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

    Irreversible: removes the account along with every lexicon, course, and
    answer it owns. The caller's token becomes useless once the user is gone.
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
    """List the authenticated user's lexicons, sorted by vocabulary rate.

    The rate is computed from each lexicon's answer history (one bulk query);
    lexicons without enough data (rate `None`) sort to the end.
    """
    sequences: dict[str, list[tuple[datetime, int]]] = (
        postgres.get_lexicon_answer_sequences(user_id)
    )
    summaries: list[LexiconSummary] = []
    for (
        lexicon_id,
        language,
        selection,
        words,
        dont_last_week,
        is_main,
        name,
    ) in postgres.list_lexicons(user_id):
        _, rate_values = compute_lexicon_rate(sequences.get(lexicon_id, []))
        summaries.append(
            LexiconSummary(
                lexicon_id=lexicon_id,
                language=language,
                selection=selection,
                name=name,
                words=words,
                dont_last_week=dont_last_week,
                rate=rate_values[-1] if rate_values else None,
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


class CreateLexiconRequest(BaseModel):
    """Payload to create a lexicon: the language and its translation targets."""

    language: str
    translation_languages: list[str] = Field(default_factory=lambda: ["en"])
    selection: str = "frequency"
    """Word-selection strategy; one of `LEXICON_STRATEGIES`."""


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
    frequency list, shows usage examples from Tatoeba, and translates words into
    the requested target languages. Its id is the language code, suffixed if one
    already exists. If the language has no main lexicon yet, the new one is set
    as main so it shows up on the home page at once; an existing main lexicon
    keeps its status.
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

    data = get_data()
    frequency_list: dict | None = data.get_frequency_list_languages().get(
        request.language
    )
    if frequency_list is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"No frequency list available for language "
                f"`{request.language}`."
            ),
        )

    targets: list[str] = [
        target
        for target in dict.fromkeys(request.translation_languages)
        if _is_known_language(target)
    ]
    if not targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one valid translation language is required.",
        )

    existing: set[str] = {row[0] for row in postgres.list_lexicons(user_id)}
    lexicon_id: str = request.language
    suffix: int = 2
    while lexicon_id in existing:
        lexicon_id = f"{request.language}_{suffix}"
        suffix += 1

    with_kaikki: bool = (
        "en" in targets
        and data.dictionaries.can_download_kaikki(
            Language.from_code(request.language)
        )
    )
    dictionaries, sentences = _translation_config(
        request.language, targets, with_kaikki=with_kaikki
    )
    config: dict = {
        "language": request.language,
        "selection": selection.value,
        "frequency_list": frequency_list,
        "precision_per_week": 0,
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
    precision_per_week: int  # Weekly goal of new answers.


class UpdateLexiconRequest(BaseModel):
    """Partial update to a lexicon's settings; omitted fields are unchanged."""

    lexicon_id: str | None = Field(default=None, pattern=LEXICON_ID_PATTERN)
    name: str | None = None  # An empty (or blank) name clears it.
    translation_languages: list[str] | None = None
    precision_per_week: int | None = Field(default=None, ge=0)


def _lexicon_translation_languages(config: dict) -> list[str]:
    """Derive a lexicon's translation targets from its stored config.

    Unlike a course (`base_languages`), a lexicon does not store its targets
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


def _lexicon_settings(lexicon_id: str, config: dict) -> LexiconSettings:
    """Read a lexicon's editable settings out of its flat config."""
    return LexiconSettings(
        lexicon_id=lexicon_id,
        language=config["language"],
        selection=config["selection"],
        name=config.get("name"),
        translation_languages=_lexicon_translation_languages(config),
        precision_per_week=config.get("precision_per_week") or 0,
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

    if request.precision_per_week is not None:
        config["precision_per_week"] = request.precision_per_week

    if request.translation_languages is not None:
        targets: list[str] = [
            target
            for target in dict.fromkeys(request.translation_languages)
            if _is_known_language(target)
        ]
        if not targets:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one valid translation language is required.",
            )
        language: str = config["language"]
        with_kaikki: bool = (
            "en" in targets
            and get_data().dictionaries.can_download_kaikki(
                Language.from_code(language)
            )
        )
        dictionaries, sentences = _translation_config(
            language, targets, with_kaikki=with_kaikki
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


class CreateCourseRequest(BaseModel):
    """Payload to create a learning course: language and translation targets."""

    language: str
    translation_languages: list[str] = Field(default_factory=lambda: ["en"])


class CreatedCourse(BaseModel):
    """The identifier assigned to a freshly created course."""

    course_id: str


@app.post("/api/v1/me/courses", status_code=status.HTTP_201_CREATED)
def create_course(
    request: CreateCourseRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> CreatedCourse:
    """Create a learning course for a language.

    New words are drawn from the language's frequency list (skipping ones a
    dictionary marks uncommon), shown with Tatoeba usage examples, and
    translated into the requested target languages — the same shared data a
    lexicon uses. Its id is the language code, suffixed if one already exists.
    """
    data = get_data()
    frequency_list: dict | None = data.get_frequency_list_languages().get(
        request.language
    )
    if frequency_list is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"No frequency list available for language "
                f"`{request.language}`."
            ),
        )

    targets: list[str] = [
        target
        for target in dict.fromkeys(request.translation_languages)
        if _is_known_language(target)
    ]
    if not targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one valid translation language is required.",
        )

    existing: set[str] = {row[0] for row in postgres.list_courses(user_id)}
    course_id: str = request.language
    suffix: int = 2
    while course_id in existing:
        course_id = f"{request.language}_{suffix}"
        suffix += 1

    with_kaikki: bool = (
        "en" in targets
        and data.dictionaries.can_download_kaikki(
            Language.from_code(request.language)
        )
    )
    dictionaries, sentences = _translation_config(
        request.language, targets, with_kaikki=with_kaikki
    )
    # New words come from the frequency list; when a Kaikki dictionary is
    # available it also filters out words it marks uncommon (mere word forms).
    new_question: dict = {"pick_from": [frequency_list]}
    if with_kaikki:
        new_question["ignore_not_common"] = [
            {
                "id": "kaikki",
                "from_language": request.language,
                "name": kaikki_language_name(
                    Language.from_code(request.language)
                ),
            }
        ]
    config: dict = {
        "name": Language.from_code(request.language).get_name(),
        "learning_language": request.language,
        "base_languages": targets,
        "scheme": {"new_question": new_question},
        "dictionaries": dictionaries,
        "sentences": sentences,
        "audio": data.get_audio_config(request.language),
    }
    postgres.store_learn_config(user_id, course_id, config)
    return CreatedCourse(course_id=course_id)


@app.delete(
    "/api/v1/me/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_course(
    course_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> None:
    """Delete a course and all its answer history.

    Irreversible: removes the course along with every record and session it
    owns. Responds 404 when the user has no such course.
    """
    if not postgres.delete_course(user_id, course_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown course `{course_id}`.",
        )
    LEARNING_REGISTRY.invalidate(user_id, course_id)


class CourseSettings(BaseModel):
    """A course's editable settings."""

    name: str
    learning_language: str
    translation_languages: list[str]  # `base_languages`.
    max_for_day: int  # New words introduced per day.
    play_audio: bool  # Whether to play pronunciation audio in a session.


class UpdateCourseRequest(BaseModel):
    """Partial update to a course's settings; omitted fields are unchanged."""

    name: str | None = None
    translation_languages: list[str] | None = None
    max_for_day: int | None = Field(default=None, ge=0)
    play_audio: bool | None = None


def _course_settings(config: dict) -> CourseSettings:
    """Read a course's editable settings out of its flat config."""
    return CourseSettings(
        name=config["name"],
        learning_language=config["learning_language"],
        translation_languages=config.get("base_languages") or [],
        max_for_day=config.get("max_for_day", 10),
        play_audio=config.get("play_audio", True),
    )


@app.get("/api/v1/me/courses/{course_id}/settings")
def get_course_settings(
    course_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> CourseSettings:
    """Get a course's editable settings (to pre-fill an edit form)."""
    return _course_settings(_course_config_or_404(user_id, course_id))


@app.patch("/api/v1/me/courses/{course_id}/settings")
def update_course_settings(
    course_id: str,
    request: UpdateCourseRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> CourseSettings:
    """Update a course's settings; omitted fields keep their current value.

    Changing the translation languages regenerates the derived translation and
    audio config (dictionaries, sentences, audio) from the same builders course
    creation uses. The course's `learning_language` is immutable and its answer
    history is untouched (records carry their own provenance).
    """
    config: dict = _course_config_or_404(user_id, course_id)
    data = get_data()

    if request.name is not None:
        name: str = request.name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Course name cannot be empty.",
            )
        config["name"] = name

    if request.max_for_day is not None:
        config["max_for_day"] = request.max_for_day

    if request.play_audio is not None:
        config["play_audio"] = request.play_audio

    if request.translation_languages is not None:
        targets: list[str] = [
            target
            for target in dict.fromkeys(request.translation_languages)
            if _is_known_language(target)
        ]
        if not targets:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one valid translation language is required.",
            )
        language: str = config["learning_language"]
        with_kaikki: bool = (
            "en" in targets
            and data.dictionaries.can_download_kaikki(
                Language.from_code(language)
            )
        )
        dictionaries, sentences = _translation_config(
            language, targets, with_kaikki=with_kaikki
        )
        config["base_languages"] = targets
        config["dictionaries"] = dictionaries
        config["sentences"] = sentences
        config["audio"] = data.get_audio_config(language)

    postgres.store_learn_config(user_id, course_id, config)
    # The cached instance (if any) was built on the old settings.
    LEARNING_REGISTRY.invalidate(user_id, course_id)
    return _course_settings(config)


class NextWord(BaseModel):
    """The next word to check, or `None` when the list is exhausted."""

    word: str | None


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


# Short human labels for stored response codes, for the "last answer" hint.
_LEXICON_RESPONSE_LABELS: dict[str, str] = {
    LexiconResponse.KNOW.to_code(): "know",
    LexiconResponse.DONT.to_code(): "don't know",
    LexiconResponse.DONT_BUT_PROPER_NOUN_TOO.to_code(): "proper noun",
    LexiconResponse.NOT_A_WORD.to_code(): "not a word",
}
_LEARN_RESPONSE_LABELS: dict[str, str] = {
    Response.RIGHT.value: "right",
    Response.WRONG.value: "wrong",
    Response.SKIP.value: "skip",
}


def _word_cards(
    words: list[str],
    answers: dict[str, tuple[str, datetime]],
    labels: dict[str, str],
    *,
    typed: bool = False,
) -> list[WordCard]:
    """Build word cards, attaching each word's last answer.

    :param typed: whether the card is answered by typing the word (learning),
        in which case `accepted` is populated so the client can auto-accept a
        correct entry; lexicon cards leave it `None`.
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
                accepted=[word] if typed else None,
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


def _course_sentence(
    word: str,
    language: str,
    configs: list[dict] | None,
    base_languages: list[str],
) -> tuple[int, str, str] | None:
    """One example sentence (word blanked) plus one of its translations.

    Only sentences that have a translation into one of the course's base
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


def _dictionary_configs(
    dictionaries: list[dict] | None,
) -> list[DictionaryUsageConfig]:
    """Parse a lexicon/course's raw dictionary configs, preserving order."""
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

    When ``index`` is given, only the dictionary at that position in the
    configured list is queried; this lets the client load each dictionary
    independently and reveal them as they arrive, rather than waiting for the
    slowest one. ``None`` queries every configured dictionary. With
    ``hide_word`` the word is blanked out of the definitions, so they can serve
    as a learning prompt without revealing the answer.
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

    index: int  # Position in the lexicon/course's dictionary list.
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


def _frequency_list_or_error(config: dict, lexicon_id: str) -> FrequencyList:
    """Resolve a lexicon's configured frequency list or raise an HTTP error."""
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
    return frequency_list


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
    try:
        session = LEXICON_SESSIONS.open(
            user_id,
            lexicon_id,
            config["language"],
            LexiconSelection(config["selection"]),
            frequency_list,
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
                    frequency_list, pool, selection, selector_states
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
            card.stratum = stratum_of_rank(card.rank, size)
    return NextWords(
        language=language,
        words=cards,
        selection=selection,
        list_size=size,
        strata=(
            DEFAULT_N_STRATA
            if selection == LexiconSelection.STRATIFIED
            else None
        ),
    )


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


@app.get("/api/v1/me/lexicons/{lexicon_id}/rate-estimate")
def get_lexicon_rate_estimate(
    lexicon_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> RateEstimate:
    """Estimate the lexicon's vocabulary rate with its standard deviation.

    Unlike the plain `rate` field of the stats endpoints (which applies the
    frequency-weighted sliding window to every log), this dispatches to the
    estimator matching the lexicon's selection strategy — the window estimate
    is unbiased only over frequency-weighted draws. Refreshed by the check
    page after every answer.
    """
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    selection: LexiconSelection = LexiconSelection(config["selection"])
    method: RateEstimator | None = RATE_ESTIMATOR_BY_SELECTION.get(selection)
    if method is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"No rate estimator for selection `{selection}`.",
        )

    if method == RateEstimator.FREQUENCY:
        estimate: tuple[float, float] | None = estimate_rate_with_sd(
            selection,
            sequence=postgres.get_lexicon_answer_sequence(user_id, lexicon_id),
        )
    else:
        # The model-based estimators place every word by frequency rank, so
        # they need the lexicon's frequency list and the same lexicon-scoped
        # states that seed word selection: the estimate must reflect this
        # lexicon's own sample, not answers collected under sibling lexicons'
        # strategies.
        if config["frequency_list"] is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Lexicon `{lexicon_id}` has no frequency list configured."
                ),
            )
        frequency_list = get_data().get_frequency_list(
            ListUsageConfig(**config["frequency_list"])
        )
        if frequency_list is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Configured frequency list could not be loaded.",
            )
        states: dict[str, tuple[str | None, bool | None]] = (
            postgres.get_lexicon_selector_states(user_id, lexicon_id)
        )
        estimate = estimate_rate_with_sd(selection, frequency_list, states)

    if estimate is None:
        return RateEstimate(rate=None, sd=None, method=method)
    return RateEstimate(rate=estimate[0], sd=estimate[1], method=method)


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

    ``index`` optionally restricts the result to the single dictionary at that
    position (see ``/dictionaries``), so the client can load each dictionary
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
    """A translation of the sentence (course learning only), else `None`."""
    sentence_id: int | None = None
    """The example's id (course learning only), recorded with the answer."""


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
    is_main: bool  # Main lexicon for its language.


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
        is_main=postgres.is_main_lexicon(user_id, lexicon_id),
    )


class LanguageRate(BaseModel):
    """A language's level: the rate of its main lexicon."""

    language: str
    lexicon_id: str  # The main lexicon the rate comes from.
    rate: float | None  # Vocabulary rate, or None if not enough data.
    weekly_remaining: int  # Weekly precision goal minus this week's progress.
    last_dont_know: datetime | None  # Time of the last "don't know" answer.


@app.get("/api/v1/me/languages")
def get_my_languages(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[LanguageRate]:
    """List the user's languages and their level (the main lexicon's rate)."""
    sequences: dict[str, list[tuple[datetime, int]]] = (
        postgres.get_lexicon_answer_sequences(user_id)
    )
    rates: list[LanguageRate] = []
    for (
        language,
        lexicon_id,
        precision_per_week,
        dont_last_week,
    ) in postgres.get_main_lexicons(user_id):
        sequence = sequences.get(lexicon_id, [])
        _, rate_values = compute_lexicon_rate(sequence)
        last_dont_know = next(
            (time for time, response in reversed(sequence) if response == 0),
            None,
        )
        rates.append(
            LanguageRate(
                language=language,
                lexicon_id=lexicon_id,
                rate=rate_values[-1] if rate_values else None,
                weekly_remaining=precision_per_week - dont_last_week,
                last_dont_know=last_dont_know,
            )
        )
    rates.sort(
        key=lambda r: r.rate if r.rate is not None else float("-inf"),
        reverse=True,
    )
    return rates


GRAPH_GRID_COLOR: Color = Color("#888888")
"""Grid color legible on both the light and the dark page theme."""


@app.get("/api/v1/me/lexicons/graph")
def get_lexicons_graph(
    request: Request, user_id: Annotated[str, Depends(get_current_user)]
) -> HTTPResponse:
    """Render the rate history of the user's main lexicons as an SVG graph.

    The background is transparent so the graph can be inlined into a page and
    inherit its theme. The `ETag` is derived from the newest lexicon record:
    the history only changes when the user answers (or undoes) a lexicon
    check, so a matching `If-None-Match` skips loading the records and
    rendering entirely.

    Responds 204 when there is not enough data to plot anything yet.
    """
    last_record_id: int | None = postgres.get_last_lexicon_record_id(user_id)
    etag: str = f'"lexicon-graph-{last_record_id or 0}"'
    if request.headers.get("if-none-match") == etag:
        return HTTPResponse(
            status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag}
        )

    sequences: dict[str, list[tuple[datetime, int]]] = (
        postgres.get_lexicon_answer_sequences(user_id)
    )
    data: dict[Language, list[tuple[datetime, int]]] = {}
    for language, lexicon_id, _, _ in postgres.get_main_lexicons(user_id):
        sequence = sequences.get(lexicon_id)
        if not sequence:
            continue
        try:
            data[Language.from_code(language)] = sequence
        except LanguageNotFoundError:
            continue

    visualizer: LexiconVisualizer = LexiconVisualizer(interactive=False)
    x_min, x_max, lexicon_data = visualizer.construct_data_from_sequences(
        data, margin=None
    )
    svg = visualizer.build_svg(
        x_min,
        x_max,
        lexicon_data,
        colors=None,
        background_color=None,
        grid_color=GRAPH_GRID_COLOR,
    )
    if svg is None:
        return HTTPResponse(status_code=status.HTTP_204_NO_CONTENT)

    return HTTPResponse(
        content=svg.tostring(),
        media_type="image/svg+xml",
        headers={"ETag": etag, "Cache-Control": "private, no-cache"},
    )


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


# Learning. Only the spaced-repetition review of words already being learned is
# served; adding new words needs the interactive `Teacher` and is not yet here.


def _learning_entry(user_id: str, course_id: str) -> LearningEntry:
    """Get the user's course from the per-process cache.

    Replaying every record of a course on each request does not scale; the
    registry caches the loaded `Learning` and reloads it only when its
    freshness stamp shows records arrived through another path (undo, CLI).
    Use the entry's lock around any access to the instance.
    """
    config: dict = _course_config_or_404(user_id, course_id)
    return LEARNING_REGISTRY.entry(user_id, course_id, config)


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
    entry: LearningEntry = _learning_entry(user_id, course_id)
    with entry.lock:
        learning: Learning = entry.learning
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
def get_next_questions(
    course_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    count: int = 1,
    exclude: Annotated[list[str] | None, Query()] = None,
) -> NextWords:
    """Get the next words due for repetition, soonest-due first.

    `count` lets the client prefetch a queue; `exclude` lists words already
    queued so the batch has no duplicates.
    """
    entry: LearningEntry = _learning_entry(user_id, course_id)
    with entry.lock:
        language: str = entry.learning.learning_language.get_code()
        questions: list[str] = entry.learning.get_next_questions(
            max(1, min(count, _BATCH_MAX)), set(exclude or [])
        )
    answers = postgres.get_last_learn_answers(user_id, course_id, questions)
    return NextWords(
        language=language,
        words=_word_cards(
            questions, answers, _LEARN_RESPONSE_LABELS, typed=True
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

# Multiple-choice and connect sizes.
_CHOICE_OPTIONS: int = 4
_CONNECT_SIZE: int = 4
# Due words to consider when forming one question.
_QUESTION_BATCH: int = 12


class CourseAnswerRequest(BaseModel):
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
    "/api/v1/me/courses/{course_id}/answer",
    status_code=status.HTTP_204_NO_CONTENT,
)
def answer_question(
    course_id: str,
    request: CourseAnswerRequest,
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
    entry: LearningEntry = _learning_entry(user_id, course_id)
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


class OpenCourseSessionRequest(BaseModel):
    """Payload to open a learning session."""

    type: str = "repeat_and_learn_new"
    """Session type stored in the log (mirrors the CLI teacher's types)."""


@app.post(
    "/api/v1/me/courses/{course_id}/sessions",
    status_code=status.HTTP_201_CREATED,
)
def open_course_session(
    course_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    request: OpenCourseSessionRequest | None = None,
) -> OpenedSession:
    """Open a learning session on the course.

    Answers carrying the returned identifier are grouped into one
    `learn_sessions` row (start, end, action count) when the session closes —
    the same bookkeeping the CLI teacher does. Opening also warms the cached
    course, so the first question arrives without replaying the records.
    """
    config: dict = _course_config_or_404(user_id, course_id)
    session = LEARNING_REGISTRY.open_session(
        user_id,
        course_id,
        config,
        request.type if request is not None else "repeat_and_learn_new",
    )
    return OpenedSession(session_id=session.session_id)


@app.post(
    "/api/v1/me/courses/{course_id}/sessions/{session_id}/close",
    status_code=status.HTTP_204_NO_CONTENT,
)
def close_course_session(
    course_id: str,
    session_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> None:
    """Close the learning session, writing its log row.

    Idempotent: closing an unknown or already-closed session is a no-op, so
    client retries are safe. A session that is never closed is finalized when
    it expires or the server shuts down; a session without answers leaves no
    row.
    """
    _course_config_or_404(user_id, course_id)
    LEARNING_REGISTRY.close_session(user_id, course_id, session_id)


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


def _streak(learning: Learning, word: str) -> int:
    """Get the word's run of correct answers (0 if new or last was wrong)."""
    knowledge = learning.get_knowledge(word)
    return knowledge.count_right_streak() if knowledge else 0


def _single_question_type(
    streak: int, enabled: set[str], *, choice_feasible: bool
) -> str:
    """Pick a single-word question type for a word by its knowledge.

    The hardest enabled, feasible type the word has earned by its streak; if it
    has earned none, the easiest enabled, feasible type. `type_word` is always
    feasible, so a type is always returned.
    """

    def feasible(question_type: str) -> bool:
        if question_type not in enabled:
            return False
        if question_type == QUESTION_TYPE_CHOICE:
            return choice_feasible
        return True  # `know` and `type_word` need no extra data.

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


@app.get("/api/v1/me/courses/{course_id}/question")
async def get_question(
    course_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    exclude: Annotated[list[str] | None, Query()] = None,
) -> Question:
    """Get the next due review question, of a type chosen for the words.

    The type is decided by the course's configured `question_types`, by each
    word's knowledge (recognition before production), and by what data exists
    (a short translation is needed for `choice`/`connect`). New words are not
    served here — they come from `/new`. `type` is `None` when nothing is due.
    """
    entry: LearningEntry = _learning_entry(user_id, course_id)
    with entry.lock:
        learning: Learning = entry.learning
        language: str = learning.learning_language.get_code()
        due: list[str] = learning.get_next_questions(
            _QUESTION_BATCH, set(exclude or [])
        )
        # Snapshot the streaks under the lock: the translation lookups below
        # await, and the instance may take answers meanwhile.
        streaks: dict[str, int] = {
            word: _streak(learning, word) for word in due
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
    if QUESTION_TYPE_CONNECT in enabled:
        matchable: list[str] = [
            word for word in due if word in translatable and streaks[word] <= 1
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
        streaks[word], enabled, choice_feasible=choice_feasible
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
        )
    if question_type == QUESTION_TYPE_KNOW:
        return Question(
            type=QUESTION_TYPE_KNOW, language=language, words=[word]
        )
    return Question(
        type=QUESTION_TYPE_TYPE_WORD,
        language=language,
        words=[word],
        accepted=[word],
    )


@app.post("/api/v1/me/courses/{course_id}/undo")
def undo_course_answer(
    course_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> NextWord:
    """Undo the most recent answer in the course, returning its word.

    Lets a mis-clicked repetition answer be corrected by re-answering.
    """
    _course_config_or_404(user_id, course_id)
    word: str | None = postgres.delete_last_learn_record(user_id, course_id)
    # The delete bypassed the cached instance; drop it so the next request
    # reloads from ground truth.
    LEARNING_REGISTRY.invalidate(user_id, course_id)
    return NextWord(word=word)


@app.get("/api/v1/me/courses/{course_id}/dictionaries")
def get_course_dictionaries(
    course_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> list[DictionaryInfo]:
    """List the course's dictionaries so the client can load each separately."""
    config: dict = _course_config_or_404(user_id, course_id)
    return _dictionary_infos(config.get("dictionaries"))


@app.get("/api/v1/me/courses/{course_id}/translation")
async def get_course_translation(
    course_id: str,
    word: str,
    user_id: Annotated[str, Depends(get_current_user)],
    index: int | None = None,
    hide_word: bool = True,  # noqa: FBT001, FBT002
) -> Translation:
    """Get a word's translation from the course's configured dictionaries.

    With ``hide_word`` (the default) the word is blanked out of the definitions,
    so the meaning serves as a recall prompt without revealing the answer — used
    by the type-the-word question. The know question passes ``hide_word=false``
    to show the full meaning once the user has self-assessed. ``index``
    optionally restricts the result to one dictionary (see ``/dictionaries``).
    """
    config: dict = _course_config_or_404(user_id, course_id)
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


@app.get("/api/v1/me/courses/{course_id}/sentence")
def get_course_sentence(
    course_id: str,
    word: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> Sentence:
    """Get one example sentence for a word, blanked, with a translation.

    A recall prompt: the word is blanked out and the sentence comes with one of
    its translations into a base language (only translated sentences are used).
    A slow lookup kept off `/next` so the card appears immediately and the
    example is revealed when it arrives.
    """
    config: dict = _course_config_or_404(user_id, course_id)
    result: tuple[int, str, str] | None = _course_sentence(
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


@app.get("/api/v1/me/courses/{course_id}/audio")
def get_course_audio(
    course_id: str,
    word: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> FileResponse:
    """Stream a pronunciation recording for a word in the course's language.

    Returns the first available recording across the course's configured audio
    providers, in priority order (local directories first; Wikimedia Commons,
    which downloads on demand, last). Responds 404 when the course has audio
    playback disabled, no audio configured, or no recording is found.
    """
    config: dict = _course_config_or_404(user_id, course_id)
    if not config.get("play_audio", True):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio playback is disabled for this course.",
        )
    audio_configs: list[dict] | None = config.get("audio")
    if not audio_configs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No audio configured for this course.",
        )
    collection = get_data().get_audio_collection(
        [AudioUsageConfig(**audio) for audio in audio_configs]
    )
    # Ask providers one at a time and stop at the first hit, so a local file
    # short-circuits the on-demand Wikimedia download of a later provider.
    path: Path | None = None
    with log_duration(f"audio lookup for `{word}` ({course_id})", logger):
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
    with log_duration(f"audio transcode for `{word}` ({course_id})", logger):
        path = to_browser_playable(
            path, get_data().get_audio_data().path / "cache" / "browser"
        )
    return FileResponse(
        path, media_type=_AUDIO_MEDIA_TYPES.get(path.suffix.lower())
    )


class NewQuestion(BaseModel):
    """The next new word to add to a course, or `None` when none remains."""

    word: str | None
    accepted: list[str] | None = None  # Typed answers that count as correct.
    check_lexicon: str | None = None
    """Lexicon to ask know/don't-know in *before* learning this word.

    Set when the course has an `ask_lexicon` and the word has not been answered
    there yet: the client first presents a yes/no check and posts the answer to
    that lexicon's `/answer`. "Know" means skip the word (request `/new` again);
    "don't know" admits it to learning. `None` means learn the word directly.
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
    """Whether a word is worth learning per the course's dictionaries.

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


@app.get("/api/v1/me/courses/{course_id}/new")
async def get_new_question_word(
    course_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    exclude: Annotated[list[str] | None, Query()] = None,
) -> NewQuestion:
    """Get the next new word to add to a course, from its question lists.

    Ports the selection half of `Teacher`: walks the configured frequency lists
    in order and returns the first candidate worth learning, skipping words
    already being learned, already known in a `check_lexicons` lexicon, or not
    common per the configured dictionaries. A word marked "don't know" in a
    check lexicon is returned to learn directly; otherwise, when an
    `ask_lexicon` is configured and the word is new there, it is returned with
    `check_lexicon` set so the client first asks the user know/don't-know.

    Stateless: it re-scans from the top each call (the in-memory skips are
    cheap), so an answered or admitted word simply stops being returned next
    time. Returns `word=None` when the daily limit is reached, the course has no
    new-question scheme, or the lists are exhausted.
    """
    entry: LearningEntry = _learning_entry(user_id, course_id)
    with entry.lock:
        learning: Learning = entry.learning
        remaining: int = learning.count_questions_to_add()
    scheme = learning.config.scheme
    if (
        remaining <= 0
        or scheme is None
        or scheme.new_question is None
        or not scheme.new_question.pick_from
    ):
        return NewQuestion(word=None, remaining_today=max(0, remaining))

    new_question = scheme.new_question
    data = get_data()

    # Candidate words, list-then-rank order (mirrors `Teacher.question_ids`).
    candidates: list[str] = []
    for list_config in new_question.pick_from:
        word_list = data.get_list(list_config)
        if word_list is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Question list `{list_config.id}` could not be loaded.",
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
        return NewQuestion(
            word=word,
            accepted=[word],
            check_lexicon=check_lexicon,
            remaining_today=remaining,
        )

    return NewQuestion(word=None, remaining_today=remaining)


# Serve shared documentation assets (logo, headers) read-only, so the web
# interface can reuse them without duplicating the files into `web/`.
_DOC_DIR: Path = Path(__file__).resolve().parents[2] / "doc"
app.mount("/doc", StaticFiles(directory=_DOC_DIR), name="doc")

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
