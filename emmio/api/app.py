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
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import jwt
from fastapi import Depends, FastAPI, Form, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from emmio import postgres
from emmio.api import auth
from emmio.api.render import elements_to_html, to_html
from emmio.data import Data
from emmio.dictionary.config import DictionaryUsageConfig
from emmio.language import KnownLanguages, Language
from emmio.learn.config import LearnConfig
from emmio.learn.core import Learning, Response
from emmio.lexicon.config import LexiconConfig
from emmio.lexicon.core import (
    AnswerType,
    Lexicon,
    LexiconResponse,
    compute_lexicon_rate,
    select_next_word,
)
from emmio.lists.config import ListUsageConfig
from emmio.sentence.config import SentencesUsageConfig
from emmio.sentence.core import SentenceElement
from emmio.ui import Element, Formatted, Text

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
    ) in postgres.list_lexicons(user_id):
        _, rate_values = compute_lexicon_rate(sequences.get(lexicon_id, []))
        summaries.append(
            LexiconSummary(
                lexicon_id=lexicon_id,
                language=language,
                selection=selection,
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


class NextWord(BaseModel):
    """The next word to check, or `None` when the list is exhausted."""

    word: str | None


class WordCard(BaseModel):
    """One upcoming word with its last-answer context (if any)."""

    word: str
    last_response: str | None  # Human label of the last answer, e.g. "know".
    last_time: datetime | None  # When the word was last answered.
    sentence: str | None  # Example-sentence HTML (word in bold), if available.


class NextWords(BaseModel):
    """A batch of upcoming words, soonest first; empty when exhausted.

    Lets the client prefetch a queue instead of fetching one word per answer.
    """

    words: list[WordCard]


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
    sentences: dict[str, str | None] | None = None,
) -> list[WordCard]:
    """Build word cards, attaching each word's last answer and example."""
    sentences = sentences or {}
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
                sentence=sentences.get(word),
            )
        )
    return cards


def _sentence_html(
    word: str, language: str, configs: list[dict] | None
) -> str | None:
    """Render one example sentence for a word, with the word in bold.

    Mirrors the CLI's usage example: a sentence in the lexicon's language with
    the target word highlighted (its translation is intentionally not shown).
    Returns `None` if the lexicon has no sentence sources or none are found.
    """
    if not configs:
        return None
    examples = (
        get_data()
        .get_sentences_data()
        .get(word, [SentencesUsageConfig(**config) for config in configs])
    )
    if not examples:
        return None
    language_object: Language = Language.from_code(language)
    sentence = random.choice(examples).sentence
    text: Text = Text()
    for part, element in sentence.get_words(language_object):
        if (
            element == SentenceElement.WORD
            and language_object.normalize(part) == word
        ):
            text.add(Formatted(part, "bold"))
        else:
            text.add(part)
    return to_html(text)


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
) -> list[DictionaryTranslation]:
    """Look a word up, rendering each dictionary's output separately."""

    collection = get_data().get_dictionaries(
        [DictionaryUsageConfig(**d) for d in dictionaries or []]
    )
    groups: list[
        tuple[str, list[Element]]
    ] = await collection.to_text_by_dictionary(
        word, Language.from_code(language), _DEFINITION_LANGUAGES
    )
    return [
        DictionaryTranslation(dictionary=name, html=elements_to_html(elements))
        for name, elements in groups
    ]


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


@app.get("/api/v1/me/lexicons/{lexicon_id}/next")
def get_next_lexicon_words(
    lexicon_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    count: int = 1,
    exclude: Annotated[list[str] | None, Query()] = None,
) -> NextWords:
    """Get the next words to check in the authenticated user's lexicon.

    Words are drawn by the lexicon's frequency strategy. Every drawn word that
    is not presented is *recorded* with the answer it can be given automatically
    (already known/skipped/foreign/recently answered) rather than excluded, so
    the records stay a faithful frequency-weighted sample and the rate is
    computed correctly. `count` requests how many words to present; `exclude`
    lists words already queued on the client.
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
    language: str = config["language"]
    selection: str = config["selection"]
    symbols: str | None = Language.from_code(language).get_symbols()
    states: dict[str, tuple[str | None, bool | None]] = (
        postgres.get_language_word_states(user_id, language)
    )
    recent: set[str] = postgres.get_recently_answered(user_id, lexicon_id)

    limit: int = max(1, min(count, _BATCH_MAX))
    drawn: set[str] = set(exclude or [])
    # "top" walks the list in rank order and never re-asks an answered word, so
    # exclude everything already recorded; sampling strategies re-sample, so
    # they rely on `_skip_decision` instead.
    if selection == "top":
        drawn |= postgres.get_answered_words(user_id, lexicon_id)
    words: list[str] = []
    auto: list[postgres.LexiconRecordRow] = []
    now: datetime = datetime.now(UTC)
    for _ in range(_DRAW_BUDGET):
        if len(words) >= limit:
            break
        try:
            candidate: str | None = select_next_word(
                frequency_list, drawn, selection
            )
        except NotImplementedError as error:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(error)
            ) from error
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

    if auto:
        postgres.save_lexicon(user_id, lexicon_id, language, auto, [])
    answers = postgres.get_last_lexicon_answers(user_id, lexicon_id, words)
    sentences: dict[str, str | None] = {
        word: _sentence_html(word, language, config.get("sentences"))
        for word in words
    }
    return NextWords(
        words=_word_cards(words, answers, _LEXICON_RESPONSE_LABELS, sentences)
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
    record: postgres.LexiconRecordRow = (
        request.word,
        response.to_code(),
        datetime.now(UTC),
        {"sk": True} if request.to_skip else None,
    )
    postgres.save_lexicon(user_id, lexicon_id, config["language"], [record], [])


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


@app.get("/api/v1/me/lexicons/{lexicon_id}/translation")
async def get_lexicon_translation(
    lexicon_id: str,
    word: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> Translation:
    """Get a word's translation from the lexicon's configured dictionaries."""
    config: dict = _lexicon_config_or_404(user_id, lexicon_id)
    return Translation(
        word=word,
        dictionaries=await _translate(
            word, config["language"], config["dictionaries"]
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


@app.get("/api/v1/me/languages")
def get_my_languages(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[LanguageRate]:
    """List the user's languages and their level (the main lexicon's rate)."""
    sequences: dict[str, list[tuple[datetime, int]]] = (
        postgres.get_lexicon_answer_sequences(user_id)
    )
    rates: list[LanguageRate] = []
    for language, lexicon_id in postgres.get_main_lexicons(user_id):
        _, rate_values = compute_lexicon_rate(sequences.get(lexicon_id, []))
        rates.append(
            LanguageRate(
                language=language,
                lexicon_id=lexicon_id,
                rate=rate_values[-1] if rate_values else None,
            )
        )
    return rates


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
    learning: Learning = _load_learning(user_id, course_id)
    questions: list[str] = learning.get_next_questions(
        max(1, min(count, _BATCH_MAX)), set(exclude or [])
    )
    answers = postgres.get_last_learn_answers(user_id, course_id, questions)
    return NextWords(
        words=_word_cards(questions, answers, _LEARN_RESPONSE_LABELS)
    )


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


@app.post("/api/v1/me/courses/{course_id}/undo")
def undo_course_answer(
    course_id: str, user_id: Annotated[str, Depends(get_current_user)]
) -> NextWord:
    """Undo the most recent answer in the course, returning its word.

    Lets a mis-clicked repetition answer be corrected by re-answering.
    """
    _course_config_or_404(user_id, course_id)
    return NextWord(word=postgres.delete_last_learn_record(user_id, course_id))


@app.get("/api/v1/me/courses/{course_id}/translation")
async def get_course_translation(
    course_id: str,
    word: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> Translation:
    """Get a word's translation from the course's configured dictionaries."""
    config: dict = _course_config_or_404(user_id, course_id)
    return Translation(
        word=word,
        dictionaries=await _translate(
            word, config["learning_language"], config.get("dictionaries")
        ),
    )


# Serve shared documentation assets (logo, headers) read-only, so the web
# interface can reuse them without duplicating the files into `web/`.
_DOC_DIR: Path = Path(__file__).resolve().parents[2] / "doc"
app.mount("/doc", StaticFiles(directory=_DOC_DIR), name="doc")

# Serve the static web interface from the same origin as the API, so the
# browser's `fetch` calls to `/api/v1/...` need no CORS configuration. Mounted
# last so it never shadows an API route.
_WEB_DIR: Path = Path(__file__).resolve().parents[2] / "web"
app.mount("/app", StaticFiles(directory=_WEB_DIR, html=True), name="web")
