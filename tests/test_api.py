"""Tests for the HTTP API."""

import io
import json
import math
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from emmio import postgres
from emmio.api import app as app_module
from emmio.api.app import app
from emmio.api.sessions import LEXICON_SESSIONS
from emmio.dictionary.core import DictionaryCollection
from emmio.language import Language
from emmio.learn.config import LearnConfig
from emmio.learn.core import Learning
from emmio.lexicon.config import LexiconSelection
from emmio.lexicon.core import (
    DEFAULT_N_STRATA,
    StratifiedSelector,
    stratum_of_rank,
)
from emmio.lists.config import FrequencyListConfig, FrequencyListFileFormat
from emmio.lists.frequency_list import FrequencyList
from emmio.sentence.core import Sentence as ExampleSentence
from emmio.sentence.core import SentenceAndTranslations

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

client: TestClient = TestClient(app)


class _FakeDictionaries:
    """Stand-in for the dictionary inventory: no Kaikki available."""

    def can_download_kaikki(self, language: object) -> bool:  # noqa: ARG002
        return False


class _FakeData:
    """Stand-in for the shared data, with a fixed frequency-list inventory."""

    def __init__(
        self,
        languages: dict[str, dict],
        frequency_lists: dict[str, FrequencyList] | None = None,
        extra_frequency_options: list[dict] | None = None,
    ) -> None:
        self._languages = languages
        self._frequency_lists = frequency_lists or {}
        self._extra_frequency_options = extra_frequency_options or []
        self.dictionaries = _FakeDictionaries()

    def get_frequency_list_languages(self) -> dict[str, dict]:
        return self._languages

    def get_frequency_list_options(self) -> list[dict]:
        defaults = [
            {"language": language, "name": config["id"], "config": config}
            for language, config in self._languages.items()
        ]
        return defaults + self._extra_frequency_options

    def get_frequency_list(self, usage_config: Any) -> FrequencyList | None:
        return self._frequency_lists.get(usage_config.id)

    def get_sentence_languages(self) -> set[str]:
        # Every frequency-list language also has Tatoeba sentences here.
        return set(self._languages)

    def get_audio_config(self, language: str) -> list[dict]:
        # Only Wikimedia Commons here; no local providers in the fake.
        return [{"id": "wikimedia_commons", "language": language}]


@pytest.fixture
def fake_languages(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict]:
    """Make the data layer report a fixed set of frequency-list languages."""

    languages: dict[str, dict] = {
        "uk": {"id": "uk_list"},
        "la": {"id": "frequency_words", "language": "la", "year": 2022},
    }
    fake: Any = _FakeData(languages)
    monkeypatch.setattr(app_module, "get_data", lambda: fake)
    return languages


_UK_LETTERS: str = "абвгде"

_UK_WORDS: list[str] = [
    first + second for first in _UK_LETTERS for second in _UK_LETTERS
][:30]
"""Fake Ukrainian words by descending frequency: `аа` is rank 1.

All-Cyrillic on purpose: a word outside the language's alphabet would be
auto-answered as not-a-word instead of being presented.
"""


@pytest.fixture
def fake_uk_list(monkeypatch: pytest.MonkeyPatch) -> FrequencyList:
    """Serve an in-memory Ukrainian frequency list of `_UK_WORDS`."""
    frequency_list: FrequencyList = FrequencyList(
        file_path=Path("unused"),
        config=FrequencyListConfig(
            file_format=FrequencyListFileFormat.LIST,
            language="uk",
            path="unused",
            is_stripped=False,
        ),
        data={
            word: len(_UK_WORDS) - index for index, word in enumerate(_UK_WORDS)
        },
    )
    fake: Any = _FakeData(
        {"uk": {"id": "uk_list"}}, {"uk_list": frequency_list}
    )
    monkeypatch.setattr(app_module, "get_data", lambda: fake)
    return frequency_list


def _register_and_login(
    user_id: str,
    email: str,
    password: str = "secret123",  # noqa: S107  # Test fixture, not a secret.
) -> str:
    """Register a user and return a valid access token."""

    client.post(
        "/api/v1/auth/register",
        json={
            "user_id": user_id,
            "name": user_id.title(),
            "email": email,
            "password": password,
        },
    )
    response = client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    return str(response.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    """Build an authorization header from a token."""
    return {"Authorization": f"Bearer {token}"}


def test_register_returns_user() -> None:
    """Registration creates an account and echoes it back."""

    response = client.post(
        "/api/v1/auth/register",
        json={
            "user_id": "alice",
            "name": "Alice",
            "email": "alice@example.com",
            "password": "secret123",
        },
    )

    assert response.status_code == 201
    assert response.json() == {"user_id": "alice", "name": "Alice"}


def test_duplicate_registration_conflicts() -> None:
    """Registering the same login twice fails with 409."""

    payload = {
        "user_id": "alice",
        "name": "Alice",
        "email": "alice@example.com",
        "password": "secret123",
    }
    client.post("/api/v1/auth/register", json=payload)
    response = client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 409


def test_login_with_wrong_password_fails() -> None:
    """A wrong password is rejected with 401."""

    _register_and_login("alice", "alice@example.com")
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "alice@example.com", "password": "wrong"},
    )

    assert response.status_code == 401


def test_change_password_lets_user_log_in_with_new_one() -> None:
    """A changed password works for login; the old one stops working."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/password",
        json={"current_password": "secret123", "new_password": "brandnew456"},
        headers=_auth(token),
    )
    assert response.status_code == 204

    new_login = client.post(
        "/api/v1/auth/login",
        data={"username": "alice@example.com", "password": "brandnew456"},
    )
    assert new_login.status_code == 200
    old_login = client.post(
        "/api/v1/auth/login",
        data={"username": "alice@example.com", "password": "secret123"},
    )
    assert old_login.status_code == 401


def test_change_password_rejects_wrong_current() -> None:
    """The wrong current password is rejected and the password is unchanged."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/password",
        json={"current_password": "wrong", "new_password": "brandnew456"},
        headers=_auth(token),
    )
    assert response.status_code == 403

    # The original password still works.
    still = client.post(
        "/api/v1/auth/login",
        data={"username": "alice@example.com", "password": "secret123"},
    )
    assert still.status_code == 200


def test_change_password_rejects_too_short() -> None:
    """A new password below the minimum length is rejected."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/password",
        json={"current_password": "secret123", "new_password": "short"},
        headers=_auth(token),
    )
    assert response.status_code == 422


def test_change_password_requires_token() -> None:
    """Changing a password without a token is rejected with 401."""

    response = client.post(
        "/api/v1/me/password",
        json={"current_password": "a", "new_password": "brandnew456"},
    )
    assert response.status_code == 401


def test_protected_route_requires_token() -> None:
    """Accessing `/me` without a token is rejected with 401."""

    response = client.get("/api/v1/me/courses")

    assert response.status_code == 401


def test_me_courses_are_scoped_to_token_user() -> None:
    """The token determines whose data is returned."""

    alice_token = _register_and_login("alice", "alice@example.com")
    _register_and_login("bob", "bob@example.com")
    # Saving with empty records still creates the (owned) course.
    postgres.save_learning("alice", "fr", "French", "fr", [], [])

    response = client.get("/api/v1/me/courses", headers=_auth(alice_token))

    assert response.status_code == 200
    assert [course["course_id"] for course in response.json()] == ["fr"]


def test_users_cannot_see_each_others_data() -> None:
    """Bob's token never returns Alice's data."""

    _register_and_login("alice", "alice@example.com")
    bob_token = _register_and_login("bob", "bob@example.com")
    postgres.save_learning("alice", "fr", "French", "fr", [], [])

    response = client.get("/api/v1/me/courses", headers=_auth(bob_token))

    assert response.status_code == 200
    assert response.json() == []


def test_answer_records_the_word() -> None:
    """Answering a word stores it in the user's lexicon."""

    token = _register_and_login("alice", "alice@example.com")
    # Saving with empty records creates the (owned) lexicon.
    postgres.save_lexicon("alice", "de", "de", [], [])

    response = client.post(
        "/api/v1/me/lexicons/de/answer",
        json={"word": "hund", "response": "know"},
        headers=_auth(token),
    )

    assert response.status_code == 204
    assert "hund" in postgres.get_answered_words("alice", "de")


def test_answer_with_invalid_response_is_rejected() -> None:
    """An unknown response value returns 422."""

    token = _register_and_login("alice", "alice@example.com")
    postgres.save_lexicon("alice", "de", "de", [], [])

    response = client.post(
        "/api/v1/me/lexicons/de/answer",
        json={"word": "hund", "response": "maybe"},
        headers=_auth(token),
    )

    assert response.status_code == 422


def test_rate_estimate_uses_fwr_for_frequency_lexicon() -> None:
    """The rate estimate applies the estimator matching the strategy (FWR)."""

    token = _register_and_login("alice", "alice@example.com")
    # The `frequency` strategy's estimator is the FWR sliding window; it
    # needs only the answer log, not the frequency list.
    postgres.store_lexicon_config(
        "alice", "de", {"language": "de", "selection": "frequency"}
    )

    response = client.get(
        "/api/v1/me/lexicons/de/rate-estimate", headers=_auth(token)
    )
    assert response.status_code == 200
    assert response.json() == {
        "rate": None,
        "sd": None,
        "method": "frequency",
        "achieved": False,
        "recheck_available_at": None,
    }

    # 5 unknowns among 20 answers: theta = 1/4, so r = 2.
    for index in range(20):
        client.post(
            "/api/v1/me/lexicons/de/answer",
            json={
                "word": f"wort{index}",
                "response": "dont" if index % 4 == 3 else "know",
            },
            headers=_auth(token),
        )

    estimate = client.get(
        "/api/v1/me/lexicons/de/rate-estimate", headers=_auth(token)
    ).json()
    assert estimate["method"] == "frequency"
    assert estimate["rate"] == pytest.approx(2.0)
    assert estimate["sd"] == pytest.approx(1.0 / (math.log(2) * math.sqrt(5)))


def test_rate_trajectory_replays_the_answer_history() -> None:
    """The trajectory replays the estimator over every recorded answer."""

    token = _register_and_login("alice", "alice@example.com")
    postgres.store_lexicon_config(
        "alice", "de", {"language": "de", "selection": "frequency"}
    )

    # 5 unknowns among 20 answers: theta = 1/4, so r = 2 (see the rate
    # estimate test above).
    for index in range(20):
        client.post(
            "/api/v1/me/lexicons/de/answer",
            json={
                "word": f"wort{index}",
                "response": "dont" if index % 4 == 3 else "know",
            },
            headers=_auth(token),
        )

    response = client.get(
        "/api/v1/me/lexicons/de/rate-trajectory", headers=_auth(token)
    )
    assert response.status_code == 200
    trajectory = response.json()
    assert trajectory["method"] == "frequency"
    assert trajectory["total"] == 20
    # 20 answers is under the checkpoint cap, so every answer is one.
    assert [point["queries"] for point in trajectory["checkpoints"]] == list(
        range(1, 21)
    )
    # The final checkpoint agrees with the live `rate-estimate` value.
    last = trajectory["checkpoints"][-1]
    assert last["rate"] == pytest.approx(2.0)
    assert last["sd"] == pytest.approx(1.0 / (math.log(2) * math.sqrt(5)))
    # The stratum wheel is for the stratified strategy only.
    assert trajectory["n_strata"] is None
    assert trajectory["strata"] is None


def test_rate_trajectory_includes_strata_for_stratified_lexicon(
    fake_uk_list: FrequencyList,
) -> None:
    """The trajectory carries per-answer strata for the stratified strategy."""

    token = _register_and_login("alice", "alice@example.com")
    _create_uk_lexicon(token, "stratified")

    # Rank 1 known, rank 2 unknown, and a word outside the frequency list
    # (recorded, but invisible to the selector and so absent from the wheel).
    for word, response in (
        (_UK_WORDS[0], "know"),
        (_UK_WORDS[1], "dont"),
        ("ааа", "know"),
    ):
        client.post(
            "/api/v1/me/lexicons/uk/answer",
            json={"word": word, "response": response},
            headers=_auth(token),
        )

    trajectory = client.get(
        "/api/v1/me/lexicons/uk/rate-trajectory", headers=_auth(token)
    ).json()
    assert trajectory["method"] == "stratified"
    assert trajectory["total"] == 3
    assert trajectory["n_strata"] == DEFAULT_N_STRATA
    size = len(fake_uk_list)
    assert trajectory["strata"] == [
        {"stratum": stratum_of_rank(1, size), "know": True},
        {"stratum": stratum_of_rank(2, size), "know": False},
    ]


@pytest.mark.usefixtures("fake_uk_list")
def test_tables_show_strategy_matched_rate_for_stratified_lexicon() -> None:
    """The list and stats endpoints use the strategy-matched estimator.

    A stratified lexicon collects far fewer "don't know" answers than the
    window estimator's precision gate, but the stratified estimator has an
    answer as soon as every stratum is covered — here via a full census,
    which also pins the SD at exactly zero.
    """
    token = _register_and_login("alice", "alice@example.com")
    _create_uk_lexicon(token, "stratified")

    # Answer every word: ranks 1-20 known, the tail unknown — a census.
    for index, word in enumerate(_UK_WORDS):
        client.post(
            "/api/v1/me/lexicons/uk/answer",
            json={"word": word, "response": "know" if index < 20 else "dont"},
            headers=_auth(token),
        )

    expected = client.get(
        "/api/v1/me/lexicons/uk/rate-estimate", headers=_auth(token)
    ).json()
    assert expected["rate"] is not None

    lexicons = client.get("/api/v1/me/lexicons", headers=_auth(token)).json()
    assert len(lexicons) == 1
    assert lexicons[0]["rate"] == pytest.approx(expected["rate"])
    assert lexicons[0]["sd"] == pytest.approx(0.0)

    # The first lexicon of a language is created as its main one, so the
    # language level comes from the same estimator.
    languages = client.get("/api/v1/me/languages", headers=_auth(token)).json()
    assert len(languages) == 1
    assert languages[0]["rate"] == pytest.approx(expected["rate"])
    assert languages[0]["sd"] == pytest.approx(0.0)

    stats = client.get(
        "/api/v1/me/lexicons/uk/stats", headers=_auth(token)
    ).json()
    assert stats["rate"] == pytest.approx(expected["rate"])
    assert stats["sd"] == pytest.approx(0.0)


def test_next_without_frequency_list_is_bad_request() -> None:
    """A lexicon with no configured frequency list returns 400 for `next`."""

    token = _register_and_login("alice", "alice@example.com")
    postgres.save_lexicon("alice", "de", "de", [], [])

    response = client.get("/api/v1/me/lexicons/de/next", headers=_auth(token))

    assert response.status_code == 400


def test_next_for_unknown_lexicon_is_not_found() -> None:
    """Requesting `next` for a non-existent lexicon returns 404."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.get(
        "/api/v1/me/lexicons/ghost/next", headers=_auth(token)
    )

    assert response.status_code == 404


def test_lexicon_languages_lists_available_languages(
    fake_languages: dict[str, dict],
) -> None:
    """Only languages with a frequency list are offered, sorted by code."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.get("/api/v1/lexicon-languages", headers=_auth(token))

    assert response.status_code == 200
    assert [row["language"] for row in response.json()] == sorted(
        fake_languages
    )


@pytest.mark.usefixtures("fake_languages")
def test_create_lexicon_sets_it_as_main() -> None:
    """Creating a lexicon stores it and marks it main for its language."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/lexicons", json={"language": "uk"}, headers=_auth(token)
    )

    assert response.status_code == 201
    lexicon_id = response.json()["lexicon_id"]
    assert lexicon_id == "uk"
    assert postgres.is_main_lexicon("alice", "uk")


@pytest.mark.usefixtures("fake_languages")
def test_create_lexicon_keeps_existing_main() -> None:
    """A second lexicon for a language does not take over the main flag."""

    token = _register_and_login("alice", "alice@example.com")

    client.post(
        "/api/v1/me/lexicons", json={"language": "uk"}, headers=_auth(token)
    )
    second = client.post(
        "/api/v1/me/lexicons", json={"language": "uk"}, headers=_auth(token)
    )

    assert second.status_code == 201
    assert postgres.is_main_lexicon("alice", "uk")
    assert not postgres.is_main_lexicon("alice", second.json()["lexicon_id"])


@pytest.mark.usefixtures("fake_languages")
def test_delete_lexicon_removes_it() -> None:
    """Deleting a lexicon removes it; a second delete is a 404."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/lexicons",
        json={"language": "uk", "translation_languages": ["en"]},
        headers=_auth(token),
    )

    first = client.delete("/api/v1/me/lexicons/uk", headers=_auth(token))
    assert first.status_code == 204
    assert postgres.get_lexicon_config("alice", "uk") is None

    second = client.delete("/api/v1/me/lexicons/uk", headers=_auth(token))
    assert second.status_code == 404


@pytest.mark.usefixtures("fake_languages")
def test_create_lexicon_configures_translations_and_sentences() -> None:
    """A created lexicon gets Google Translate and Tatoeba config."""

    token = _register_and_login("alice", "alice@example.com")

    client.post(
        "/api/v1/me/lexicons",
        json={"language": "uk", "translation_languages": ["en", "ru"]},
        headers=_auth(token),
    )

    config = postgres.get_lexicon_config("alice", "uk")
    assert config is not None
    # No Kaikki here (the fake reports none); Google Translate per target.
    assert config["dictionaries"] == [
        {"id": "google_translate", "from_language": "uk", "to_language": "en"},
        {"id": "google_translate", "from_language": "uk", "to_language": "ru"},
    ]
    assert config["sentences"] == [
        {
            "id": "tatoeba",
            "language": "uk",
            "translation_languages": ["en", "ru"],
        }
    ]


@pytest.mark.usefixtures("fake_languages")
def test_update_lexicon_settings_regenerates_translation_config() -> None:
    """Editing translation targets rewrites dictionaries and sentences."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/lexicons",
        json={"language": "uk", "translation_languages": ["en"]},
        headers=_auth(token),
    )

    response = client.patch(
        "/api/v1/me/lexicons/uk/settings",
        json={"translation_languages": ["en", "ru"]},
        headers=_auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "uk"
    assert body["translation_languages"] == ["en", "ru"]

    config = postgres.get_lexicon_config("alice", "uk")
    assert config is not None
    assert config["dictionaries"] == [
        {"id": "google_translate", "from_language": "uk", "to_language": "en"},
        {"id": "google_translate", "from_language": "uk", "to_language": "ru"},
    ]
    assert config["sentences"] == [
        {
            "id": "tatoeba",
            "language": "uk",
            "translation_languages": ["en", "ru"],
        }
    ]
    # Identity is untouched.
    assert config["selection"] == "frequency"
    assert config["frequency_list"] == {"id": "uk_list"}


@pytest.mark.usefixtures("fake_languages")
def test_update_lexicon_settings_partial_leaves_others() -> None:
    """A partial update changes only the provided field."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/lexicons",
        json={"language": "uk", "translation_languages": ["en"]},
        headers=_auth(token),
    )

    response = client.patch(
        "/api/v1/me/lexicons/uk/settings",
        json={"name": "My Ukrainian"},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json()["translation_languages"] == ["en"]
    config = postgres.get_lexicon_config("alice", "uk")
    assert config is not None
    assert config["dictionaries"] == [  # Untouched.
        {"id": "google_translate", "from_language": "uk", "to_language": "en"}
    ]
    assert config["name"] == "My Ukrainian"


@pytest.mark.usefixtures("fake_languages")
def test_update_lexicon_settings_backfills_missing_targets() -> None:
    """A lexicon without translation config gets it backfilled on save.

    Lexicons created before targets were auto-configured have no dictionaries
    or sentences; their settings report no targets, and saving targets
    generates the config the same way creation would.
    """

    token = _register_and_login("alice", "alice@example.com")
    postgres.store_lexicon_config(
        "alice",
        "uk",
        {
            "language": "uk",
            "selection": "frequency",
            "frequency_list": {"id": "uk_list"},
        },
    )

    settings = client.get(
        "/api/v1/me/lexicons/uk/settings", headers=_auth(token)
    )
    assert settings.status_code == 200
    assert settings.json()["translation_languages"] == []

    response = client.patch(
        "/api/v1/me/lexicons/uk/settings",
        json={"translation_languages": ["en"]},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json()["translation_languages"] == ["en"]
    config = postgres.get_lexicon_config("alice", "uk")
    assert config is not None
    assert config["dictionaries"] == [
        {"id": "google_translate", "from_language": "uk", "to_language": "en"}
    ]
    assert config["sentences"] == [
        {"id": "tatoeba", "language": "uk", "translation_languages": ["en"]}
    ]


@pytest.mark.usefixtures("fake_languages")
def test_update_lexicon_settings_rejects_empty_targets() -> None:
    """Clearing every translation target is rejected."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/lexicons",
        json={"language": "uk", "translation_languages": ["en"]},
        headers=_auth(token),
    )

    response = client.patch(
        "/api/v1/me/lexicons/uk/settings",
        json={"translation_languages": ["xx"]},
        headers=_auth(token),
    )

    assert response.status_code == 400


@pytest.mark.usefixtures("fake_languages")
def test_update_lexicon_settings_sets_and_clears_name() -> None:
    """The display name is stored trimmed and a blank name clears it."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/lexicons",
        json={"language": "uk", "translation_languages": ["en"]},
        headers=_auth(token),
    )

    response = client.patch(
        "/api/v1/me/lexicons/uk/settings",
        json={"name": "  Ukrainian books  "},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Ukrainian books"
    lexicons = client.get("/api/v1/me/lexicons", headers=_auth(token)).json()
    assert lexicons[0]["name"] == "Ukrainian books"

    response = client.patch(
        "/api/v1/me/lexicons/uk/settings",
        json={"name": "  "},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json()["name"] is None


@pytest.mark.usefixtures("fake_languages")
def test_update_lexicon_settings_renames_identifier() -> None:
    """Renaming moves the lexicon and its history to the new identifier."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/lexicons",
        json={"language": "uk", "translation_languages": ["en"]},
        headers=_auth(token),
    )
    client.post(
        "/api/v1/me/lexicons/uk/answer",
        json={"word": "кіт", "response": "know"},
        headers=_auth(token),
    )

    response = client.patch(
        "/api/v1/me/lexicons/uk/settings",
        json={"lexicon_id": "uk_books"},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json()["lexicon_id"] == "uk_books"
    # History followed the rename; the old identifier is gone.
    assert "кіт" in postgres.get_answered_words("alice", "uk_books")
    assert postgres.get_lexicon_config("alice", "uk") is None
    old = client.get("/api/v1/me/lexicons/uk/settings", headers=_auth(token))
    assert old.status_code == 404


@pytest.mark.usefixtures("fake_languages")
def test_update_lexicon_settings_rejects_taken_identifier() -> None:
    """Renaming to another lexicon's identifier is a conflict."""

    token = _register_and_login("alice", "alice@example.com")
    for _ in range(2):  # `uk` and `uk_2`.
        client.post(
            "/api/v1/me/lexicons",
            json={"language": "uk", "translation_languages": ["en"]},
            headers=_auth(token),
        )

    response = client.patch(
        "/api/v1/me/lexicons/uk_2/settings",
        json={"lexicon_id": "uk"},
        headers=_auth(token),
    )

    assert response.status_code == 409
    assert postgres.get_lexicon_config("alice", "uk_2") is not None


@pytest.mark.usefixtures("fake_languages")
def test_update_lexicon_settings_rejects_malformed_identifier() -> None:
    """An identifier that is not a slug is rejected by validation."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/lexicons",
        json={"language": "uk", "translation_languages": ["en"]},
        headers=_auth(token),
    )

    response = client.patch(
        "/api/v1/me/lexicons/uk/settings",
        json={"lexicon_id": "Ukrainian books!"},
        headers=_auth(token),
    )

    assert response.status_code == 422


@pytest.mark.usefixtures("fake_languages")
def test_create_course_stores_learnable_config() -> None:
    """A created course draws new words from the language's frequency list."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/courses",
        json={"language": "uk", "translation_languages": ["en", "ru"]},
        headers=_auth(token),
    )

    assert response.status_code == 201
    assert response.json()["course_id"] == "uk"
    config = postgres.get_learn_config("alice", "uk")
    assert config is not None
    assert config["learning_language"] == "uk"
    assert config["base_languages"] == ["en", "ru"]
    # New words are picked from the language's frequency list.
    assert config["scheme"]["new_question"]["pick_from"] == [{"id": "uk_list"}]
    assert config["dictionaries"] == [
        {"id": "google_translate", "from_language": "uk", "to_language": "en"},
        {"id": "google_translate", "from_language": "uk", "to_language": "ru"},
    ]
    assert config["audio"] == [{"id": "wikimedia_commons", "language": "uk"}]


@pytest.mark.usefixtures("fake_languages")
def test_update_course_settings_regenerates_translation_config() -> None:
    """Editing translation targets rewrites dictionaries, sentences, audio."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/courses",
        json={"language": "uk", "translation_languages": ["en"]},
        headers=_auth(token),
    )

    response = client.patch(
        "/api/v1/me/courses/uk/settings",
        json={
            "name": "My Ukrainian",
            "translation_languages": ["en", "ru"],
            "max_for_day": 25,
        },
        headers=_auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "My Ukrainian"
    assert body["translation_languages"] == ["en", "ru"]
    assert body["max_for_day"] == 25
    assert body["extra_symbols"] == "ґєії'’"

    config = postgres.get_learn_config("alice", "uk")
    assert config is not None
    assert config["base_languages"] == ["en", "ru"]
    assert config["dictionaries"] == [
        {"id": "google_translate", "from_language": "uk", "to_language": "en"},
        {"id": "google_translate", "from_language": "uk", "to_language": "ru"},
    ]
    assert config["max_for_day"] == 25


@pytest.mark.usefixtures("fake_languages")
def test_update_course_settings_partial_leaves_others() -> None:
    """A partial update changes only the provided field."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/courses",
        json={"language": "uk", "translation_languages": ["en"]},
        headers=_auth(token),
    )

    response = client.patch(
        "/api/v1/me/courses/uk/settings",
        json={"max_for_day": 5, "play_audio": False},
        headers=_auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["translation_languages"] == ["en"]
    assert body["play_audio"] is False
    config = postgres.get_learn_config("alice", "uk")
    assert config is not None
    assert config["base_languages"] == ["en"]  # Untouched.
    assert config["max_for_day"] == 5
    assert config["play_audio"] is False


@pytest.mark.usefixtures("fake_languages")
def test_delete_course_removes_it() -> None:
    """Deleting a course removes it; a second delete is a 404."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/courses",
        json={"language": "uk", "translation_languages": ["en"]},
        headers=_auth(token),
    )

    first = client.delete("/api/v1/me/courses/uk", headers=_auth(token))
    assert first.status_code == 204
    assert postgres.get_learn_config("alice", "uk") is None

    second = client.delete("/api/v1/me/courses/uk", headers=_auth(token))
    assert second.status_code == 404


@pytest.mark.usefixtures("fake_languages")
def test_create_course_for_unknown_language_is_bad_request() -> None:
    """A language without a frequency list cannot be made into a course."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/courses", json={"language": "xx"}, headers=_auth(token)
    )

    assert response.status_code == 400


@pytest.mark.usefixtures("fake_languages")
def test_create_course_suffixes_duplicate_ids() -> None:
    """A second course for the same language gets a suffixed id."""

    token = _register_and_login("alice", "alice@example.com")

    first = client.post(
        "/api/v1/me/courses", json={"language": "uk"}, headers=_auth(token)
    )
    second = client.post(
        "/api/v1/me/courses", json={"language": "uk"}, headers=_auth(token)
    )

    assert first.json()["course_id"] == "uk"
    assert second.json()["course_id"] == "uk_2"


@pytest.mark.usefixtures("fake_languages")
def test_create_course_with_lexicon_stores_check_lexicons() -> None:
    """Passing `lexicon_id` wires the lexicon into the new-question scheme."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/lexicons", json={"language": "uk"}, headers=_auth(token)
    )

    response = client.post(
        "/api/v1/me/courses",
        json={"language": "uk", "lexicon_id": "uk"},
        headers=_auth(token),
    )

    assert response.status_code == 201
    config = postgres.get_learn_config("alice", "uk")
    assert config is not None
    assert config["scheme"]["new_question"]["check_lexicons"] == [{"id": "uk"}]


@pytest.mark.usefixtures("fake_languages")
def test_create_course_with_unknown_lexicon_is_bad_request() -> None:
    """A `lexicon_id` that does not belong to the user is rejected."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/courses",
        json={"language": "uk", "lexicon_id": "does-not-exist"},
        headers=_auth(token),
    )

    assert response.status_code == 400


@pytest.mark.usefixtures("fake_languages")
def test_create_course_with_mismatched_lexicon_language_is_bad_request() -> (
    None
):
    """A `lexicon_id` for a different language is rejected."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/lexicons", json={"language": "ru"}, headers=_auth(token)
    )

    response = client.post(
        "/api/v1/me/courses",
        json={"language": "uk", "lexicon_id": "ru"},
        headers=_auth(token),
    )

    assert response.status_code == 400


def test_frequency_lists_endpoint_flags_the_default_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/frequency-lists` lists every option and flags the default one."""

    languages = {"uk": {"id": "uk_list"}}
    extra = [
        {
            "language": "uk",
            "name": "Alt Ukrainian list",
            "config": {"id": "uk_list_alt"},
        }
    ]
    fake: Any = _FakeData(languages, extra_frequency_options=extra)
    monkeypatch.setattr(app_module, "get_data", lambda: fake)
    token = _register_and_login("alice", "alice@example.com")

    response = client.get("/api/v1/frequency-lists", headers=_auth(token))

    assert response.status_code == 200
    options = {option["id"]: option for option in response.json()}
    assert options["uk_list"]["is_default"] is True
    assert options["uk_list_alt"]["is_default"] is False
    assert options["uk_list_alt"]["language"] == "uk"


@pytest.mark.usefixtures("fake_languages")
def test_create_course_stores_the_chosen_frequency_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passing `frequency_list` overrides the language's default list."""

    languages = {"uk": {"id": "uk_list"}}
    extra = [
        {
            "language": "uk",
            "name": "Alt Ukrainian list",
            "config": {"id": "uk_list_alt"},
        }
    ]
    fake: Any = _FakeData(languages, extra_frequency_options=extra)
    monkeypatch.setattr(app_module, "get_data", lambda: fake)
    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/courses",
        json={"language": "uk", "frequency_list": {"id": "uk_list_alt"}},
        headers=_auth(token),
    )

    assert response.status_code == 201
    config = postgres.get_learn_config("alice", "uk")
    assert config is not None
    assert config["scheme"]["new_question"]["pick_from"] == [
        {"id": "uk_list_alt"}
    ]


def test_create_course_with_unknown_frequency_list_is_bad_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `frequency_list` not offered for the language is rejected."""

    fake: Any = _FakeData({"uk": {"id": "uk_list"}})
    monkeypatch.setattr(app_module, "get_data", lambda: fake)
    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/courses",
        json={"language": "uk", "frequency_list": {"id": "does-not-exist"}},
        headers=_auth(token),
    )

    assert response.status_code == 400


def test_question_types_are_listed() -> None:
    """`/question-types` serves every supported type with a label."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.get("/api/v1/question-types", headers=_auth(token))

    assert response.status_code == 200
    types = response.json()
    values = {t["value"] for t in types}
    assert values == {"know", "choice", "connect", "type_word"}
    assert all(t["label"] for t in types)


@pytest.mark.usefixtures("fake_languages")
def test_create_course_stores_name_max_for_day_play_audio_and_types() -> None:
    """Creation-time name, daily cap, audio toggle, and question types stick."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/courses",
        json={
            "language": "uk",
            "name": "  My Ukrainian  ",
            "max_for_day": 3,
            "play_audio": False,
            "question_types": ["know", "type_word"],
        },
        headers=_auth(token),
    )

    assert response.status_code == 201
    config = postgres.get_learn_config("alice", "uk")
    assert config is not None
    assert config["name"] == "My Ukrainian"
    assert config["max_for_day"] == 3
    assert config["play_audio"] is False
    assert config["scheme"]["question_types"] == ["know", "type_word"]


@pytest.mark.usefixtures("fake_languages")
def test_create_course_blank_name_falls_back_to_language_name() -> None:
    """A blank/omitted `name` still falls back to the language's own name."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/courses",
        json={"language": "uk", "name": "   "},
        headers=_auth(token),
    )

    assert response.status_code == 201
    config = postgres.get_learn_config("alice", "uk")
    assert config is not None
    assert config["name"] == Language.from_code("uk").get_name()


@pytest.mark.usefixtures("fake_languages")
def test_create_course_rejects_unsupported_question_type() -> None:
    """An unknown `question_types` entry is a 400, not silently stored."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/courses",
        json={"language": "uk", "question_types": ["know", "bogus"]},
        headers=_auth(token),
    )

    assert response.status_code == 400


@pytest.mark.usefixtures("fake_languages")
def test_create_course_with_ask_lexicon_stores_it() -> None:
    """`ask_lexicon_id` wires a separate `ask_lexicon` reference."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/lexicons", json={"language": "uk"}, headers=_auth(token)
    )

    response = client.post(
        "/api/v1/me/courses",
        json={"language": "uk", "ask_lexicon_id": "uk"},
        headers=_auth(token),
    )

    assert response.status_code == 201
    config = postgres.get_learn_config("alice", "uk")
    assert config is not None
    assert config["scheme"]["new_question"]["ask_lexicon"] == {"id": "uk"}
    assert "check_lexicons" not in config["scheme"]["new_question"]


@pytest.mark.usefixtures("fake_languages")
def test_create_course_with_unknown_ask_lexicon_is_bad_request() -> None:
    """An `ask_lexicon_id` that does not belong to the user is rejected."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/courses",
        json={"language": "uk", "ask_lexicon_id": "does-not-exist"},
        headers=_auth(token),
    )

    assert response.status_code == 400


@pytest.mark.usefixtures("fake_languages")
def test_get_course_settings_defaults_question_types_and_lexicons() -> None:
    """With nothing configured, all question types are allowed, no lexicons."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/courses", json={"language": "uk"}, headers=_auth(token)
    )

    response = client.get(
        "/api/v1/me/courses/uk/settings", headers=_auth(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["question_types"]) == {
        "know",
        "choice",
        "connect",
        "type_word",
    }
    assert body["lexicon_id"] is None
    assert body["ask_lexicon_id"] is None


@pytest.mark.usefixtures("fake_languages")
def test_update_course_settings_sets_question_types_and_lexicons() -> None:
    """Settings can add question types and both lexicon references."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/courses", json={"language": "uk"}, headers=_auth(token)
    )
    client.post(
        "/api/v1/me/lexicons", json={"language": "uk"}, headers=_auth(token)
    )

    response = client.patch(
        "/api/v1/me/courses/uk/settings",
        json={
            "question_types": ["know", "choice"],
            "lexicon_id": "uk",
            "ask_lexicon_id": "uk",
        },
        headers=_auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["question_types"] == ["know", "choice"]
    assert body["lexicon_id"] == "uk"
    assert body["ask_lexicon_id"] == "uk"

    config = postgres.get_learn_config("alice", "uk")
    assert config is not None
    assert config["scheme"]["question_types"] == ["know", "choice"]
    assert config["scheme"]["new_question"]["check_lexicons"] == [{"id": "uk"}]
    assert config["scheme"]["new_question"]["ask_lexicon"] == {"id": "uk"}


@pytest.mark.usefixtures("fake_languages")
def test_update_course_settings_clears_question_types_and_lexicons() -> None:
    """An empty list/string clears a previously set field back to unset."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/lexicons", json={"language": "uk"}, headers=_auth(token)
    )
    client.post(
        "/api/v1/me/courses",
        json={
            "language": "uk",
            "question_types": ["know"],
            "lexicon_id": "uk",
            "ask_lexicon_id": "uk",
        },
        headers=_auth(token),
    )

    response = client.patch(
        "/api/v1/me/courses/uk/settings",
        json={"question_types": [], "lexicon_id": "", "ask_lexicon_id": ""},
        headers=_auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["question_types"]) == {
        "know",
        "choice",
        "connect",
        "type_word",
    }
    assert body["lexicon_id"] is None
    assert body["ask_lexicon_id"] is None

    config = postgres.get_learn_config("alice", "uk")
    assert config is not None
    assert "question_types" not in config["scheme"]
    assert "check_lexicons" not in config["scheme"]["new_question"]
    assert "ask_lexicon" not in config["scheme"]["new_question"]


@pytest.mark.usefixtures("fake_languages")
def test_update_course_settings_rejects_unsupported_question_type() -> None:
    """An unknown question type in a settings update is a 400."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/courses", json={"language": "uk"}, headers=_auth(token)
    )

    response = client.patch(
        "/api/v1/me/courses/uk/settings",
        json={"question_types": ["bogus"]},
        headers=_auth(token),
    )

    assert response.status_code == 400


@pytest.mark.usefixtures("fake_languages")
def test_update_course_settings_rejects_unknown_lexicon() -> None:
    """A `lexicon_id`/`ask_lexicon_id` not belonging to the user is a 400."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/courses", json={"language": "uk"}, headers=_auth(token)
    )

    response = client.patch(
        "/api/v1/me/courses/uk/settings",
        json={"lexicon_id": "does-not-exist"},
        headers=_auth(token),
    )

    assert response.status_code == 400


def test_lexicon_strategies_are_listed() -> None:
    """`/lexicon-strategies` serves the selectable strategies with labels."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.get("/api/v1/lexicon-strategies", headers=_auth(token))

    assert response.status_code == 200
    strategies = response.json()
    values = {strategy["value"] for strategy in strategies}
    assert "frequency" in values
    assert {"logistic", "threshold", "stratified"} <= values
    assert all(strategy["label"] for strategy in strategies)


@pytest.mark.usefixtures("fake_languages")
def test_create_lexicon_defaults_to_frequency_selection() -> None:
    """Omitting the selection strategy stores the `frequency` default."""

    token = _register_and_login("alice", "alice@example.com")

    client.post(
        "/api/v1/me/lexicons", json={"language": "uk"}, headers=_auth(token)
    )

    config = postgres.get_lexicon_config("alice", "uk")
    assert config is not None
    assert config["selection"] == "frequency"


@pytest.mark.usefixtures("fake_languages")
def test_create_lexicon_stores_requested_selection() -> None:
    """A requested selection strategy is stored on the lexicon."""

    token = _register_and_login("alice", "alice@example.com")

    client.post(
        "/api/v1/me/lexicons",
        json={"language": "uk", "selection": "top"},
        headers=_auth(token),
    )

    config = postgres.get_lexicon_config("alice", "uk")
    assert config is not None
    assert config["selection"] == "top"


@pytest.mark.usefixtures("fake_languages")
def test_create_lexicon_rejects_unsupported_selection() -> None:
    """A selection strategy not servable over the API is rejected."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/lexicons",
        json={"language": "uk", "selection": "binary_search"},
        headers=_auth(token),
    )

    assert response.status_code == 400


@pytest.mark.usefixtures("fake_languages")
def test_create_lexicon_for_unknown_language_is_bad_request() -> None:
    """A language without a frequency list cannot be created."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.post(
        "/api/v1/me/lexicons", json={"language": "xx"}, headers=_auth(token)
    )

    assert response.status_code == 400


@pytest.mark.usefixtures("fake_languages")
def test_create_lexicon_suffixes_duplicate_ids() -> None:
    """A second lexicon for the same language gets a numbered id."""

    token = _register_and_login("alice", "alice@example.com")

    first = client.post(
        "/api/v1/me/lexicons", json={"language": "uk"}, headers=_auth(token)
    )
    second = client.post(
        "/api/v1/me/lexicons", json={"language": "uk"}, headers=_auth(token)
    )

    assert first.json()["lexicon_id"] == "uk"
    assert second.json()["lexicon_id"] == "uk_2"


def test_me_returns_profile() -> None:
    """`/me` returns the authenticated user's account details."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.get("/api/v1/me", headers=_auth(token))

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "alice",
        "name": "Alice",
        "email": "alice@example.com",
    }


def test_export_me_returns_archive_of_user_data() -> None:
    """`/me/export` returns a ZIP with the profile and the user's data."""

    token = _register_and_login("alice", "alice@example.com")
    postgres.save_lexicon("alice", "de", "de", [], [])
    client.post(
        "/api/v1/me/lexicons/de/answer",
        json={"word": "hund", "response": "know"},
        headers=_auth(token),
    )

    response = client.get("/api/v1/me/export", headers=_auth(token))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())
    assert "profile.json" in names
    assert "lexicon/de.json" in names
    profile = json.loads(archive.read("profile.json"))
    assert profile["user_id"] == "alice"
    assert profile["email"] == "alice@example.com"
    # The password hash is never exported.
    assert "hashed_password" not in profile


def test_export_me_requires_token() -> None:
    """Exporting data without a token is rejected with 401."""

    response = client.get("/api/v1/me/export")

    assert response.status_code == 401


def test_delete_me_removes_user_and_data() -> None:
    """Deleting the account removes the user and everything they own."""

    token = _register_and_login("alice", "alice@example.com")
    postgres.save_lexicon("alice", "de", "de", [], [])
    postgres.save_learning("alice", "fr", "French", "fr", [], [])
    # An actual answer creates a word and record, exercising the cascade order.
    client.post(
        "/api/v1/me/lexicons/de/answer",
        json={"word": "hund", "response": "know"},
        headers=_auth(token),
    )

    response = client.delete("/api/v1/me", headers=_auth(token))

    assert response.status_code == 204
    assert not postgres.user_exists("alice")
    assert postgres.list_lexicons("alice") == []
    assert postgres.list_courses("alice") == []


def test_delete_me_leaves_other_users_intact() -> None:
    """Deleting one account does not touch another user's data."""

    alice_token = _register_and_login("alice", "alice@example.com")
    _register_and_login("bob", "bob@example.com")
    postgres.save_lexicon("bob", "de", "de", [], [])

    client.delete("/api/v1/me", headers=_auth(alice_token))

    assert postgres.user_exists("bob")
    assert [row[0] for row in postgres.list_lexicons("bob")] == ["de"]


# Learning: adding new words, example sentences, typed-answer matching.


class _FakeWordList:
    """A frequency list returning a fixed sequence of words."""

    def __init__(self, words: list[str]) -> None:
        self._words = words

    def get_words(self) -> list[str]:
        return self._words

    def get_name(self) -> str:
        return "test list"


class _FakeSelectionData:
    """Stand-in data exposing one fixed question list and no dictionaries."""

    def __init__(self, words: list[str]) -> None:
        self._words = words

    def get_list(self, usage_config: object) -> _FakeWordList:  # noqa: ARG002
        return _FakeWordList(self._words)


def _make_course(
    user_id: str, course_id: str = "eo", *, scheme: dict | None = None
) -> None:
    """Store a minimal learning course with the given (or no) scheme."""

    postgres.store_learn_config(
        user_id,
        course_id,
        {
            "name": "Esperanto",
            "learning_language": "eo",
            "base_languages": ["en"],
            "scheme": scheme,
            "dictionaries": [],
        },
    )


def _new_question_scheme(
    *, check_lexicons: list[str] | None = None, ask_lexicon: str | None = None
) -> dict:
    """Build a `new_question` scheme picking from the fake `test_list`."""

    new_question: dict[str, Any] = {"pick_from": [{"id": "test_list"}]}
    if check_lexicons is not None:
        new_question["check_lexicons"] = [{"id": x} for x in check_lexicons]
    if ask_lexicon is not None:
        new_question["ask_lexicon"] = {"id": ask_lexicon}
    return {"new_question": new_question}


def test_new_question_for_unknown_course_is_not_found() -> None:
    """Requesting a new word for a missing course returns 404."""

    token = _register_and_login("alice", "alice@example.com")

    response = client.get("/api/v1/me/courses/ghost/new", headers=_auth(token))

    assert response.status_code == 404


def test_new_question_without_scheme_returns_none() -> None:
    """A course with no new-question scheme offers no new word."""

    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice", scheme=None)

    response = client.get("/api/v1/me/courses/eo/new", headers=_auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["word"] is None
    assert body["remaining_today"] == 10  # `max_for_day` default.


def test_new_question_skips_known_and_learning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Words already learned or known in a check lexicon are skipped."""

    token = _register_and_login("alice", "alice@example.com")
    _make_course(
        "alice",
        scheme=_new_question_scheme(check_lexicons=["cl"], ask_lexicon="al"),
    )
    # "alpha" is already known in the check lexicon.
    postgres.save_lexicon(
        "alice", "cl", "eo", [("alpha", "K", datetime.now(UTC), None)], []
    )
    # "beta" is already being learned.
    postgres.save_learning(
        "alice",
        "eo",
        "Esperanto",
        "eo",
        [("beta", "y", datetime.now(UTC), None, None)],
        [],
    )
    monkeypatch.setattr(
        app_module,
        "get_data",
        lambda: _FakeSelectionData(["alpha", "beta", "gamma"]),
    )

    response = client.get("/api/v1/me/courses/eo/new", headers=_auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["word"] == "gamma"
    # Unseen in the ask lexicon, so the client must ask know/don't-know first.
    assert body["check_lexicon"] == "al"
    assert body["accepted"] == ["gamma"]


def test_new_question_dont_in_check_learns_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A "don't know" in a check lexicon admits the word without asking."""

    token = _register_and_login("alice", "alice@example.com")
    _make_course(
        "alice",
        scheme=_new_question_scheme(check_lexicons=["cl"], ask_lexicon="al"),
    )
    postgres.save_lexicon(
        "alice", "cl", "eo", [("gamma", "D", datetime.now(UTC), None)], []
    )
    monkeypatch.setattr(
        app_module, "get_data", lambda: _FakeSelectionData(["gamma"])
    )

    response = client.get("/api/v1/me/courses/eo/new", headers=_auth(token))

    body = response.json()
    assert body["word"] == "gamma"
    assert body["check_lexicon"] is None  # Learned directly.


def test_new_question_first_exposure_is_know(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new word's first exposure is a `know` card when the course allows."""

    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice", scheme=_new_question_scheme())
    monkeypatch.setattr(
        app_module, "get_data", lambda: _FakeSelectionData(["gamma"])
    )

    response = client.get("/api/v1/me/courses/eo/new", headers=_auth(token))

    body = response.json()
    assert body["word"] == "gamma"
    assert body["question_type"] == "know"


def test_new_question_first_exposure_respects_question_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without `know` among the course's types, teaching stays `type_word`."""

    token = _register_and_login("alice", "alice@example.com")
    scheme = _new_question_scheme() | {"question_types": ["type_word"]}
    _make_course("alice", scheme=scheme)
    monkeypatch.setattr(
        app_module, "get_data", lambda: _FakeSelectionData(["gamma"])
    )

    response = client.get("/api/v1/me/courses/eo/new", headers=_auth(token))

    body = response.json()
    assert body["word"] == "gamma"
    assert body["question_type"] == "type_word"


def test_new_question_excludes_queued_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`exclude` skips words the client already has in hand."""

    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice", scheme=_new_question_scheme())
    monkeypatch.setattr(
        app_module, "get_data", lambda: _FakeSelectionData(["alpha", "beta"])
    )

    response = client.get(
        "/api/v1/me/courses/eo/new",
        params={"exclude": ["alpha"]},
        headers=_auth(token),
    )

    body = response.json()
    assert body["word"] == "beta"
    assert body["check_lexicon"] is None  # No ask lexicon configured.


def test_course_sentence_without_sources_is_null() -> None:
    """A course with no sentence sources returns no example sentence."""

    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice", scheme=None)

    response = client.get(
        "/api/v1/me/courses/eo/sentence",
        params={"word": "saluton"},
        headers=_auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["word"] == "saluton"
    assert body["sentence"] is None


class _FakeSentencesData:
    """Stand-in sentence store returning a fixed list of examples."""

    def __init__(self, examples: list[SentenceAndTranslations]) -> None:
        self._examples = examples

    def get(
        self,
        word: str,  # noqa: ARG002
        usage_configs: object,  # noqa: ARG002
        max_number: int = 1000,  # noqa: ARG002
    ) -> list[SentenceAndTranslations]:
        return self._examples


class _FakeSentenceData:
    """Stand-in data exposing only the sentence store."""

    def __init__(self, examples: list[SentenceAndTranslations]) -> None:
        self._examples = examples

    def get_sentences_data(self) -> _FakeSentencesData:
        return _FakeSentencesData(self._examples)


def test_course_sentence_requires_base_language_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only translated examples are used; the word is blanked, one shown."""

    token = _register_and_login("alice", "alice@example.com")
    postgres.store_learn_config(
        "alice",
        "fr",
        {
            "name": "French",
            "learning_language": "fr",
            "base_languages": ["en"],
            "scheme": None,
            "dictionaries": [],
            "sentences": [
                {
                    "id": "tatoeba",
                    "language": "fr",
                    "translation_languages": ["en"],
                }
            ],
        },
    )
    english = Language.from_code("en")
    french = Language.from_code("fr")
    translated = SentenceAndTranslations(
        sentence=ExampleSentence(1, "Le chat dort."),
        language=french,
        translations={english: [ExampleSentence(2, "The cat sleeps.")]},
    )
    untranslated = SentenceAndTranslations(
        sentence=ExampleSentence(3, "Un chat noir."),
        language=french,
        translations={},
    )
    monkeypatch.setattr(
        app_module,
        "get_data",
        lambda: _FakeSentenceData([untranslated, translated]),
    )

    response = client.get(
        "/api/v1/me/courses/fr/sentence",
        params={"word": "chat"},
        headers=_auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    # The translated example wins; its word is blanked and a translation shown.
    assert body["translation"] == "The cat sleeps."
    assert "chat" not in body["sentence"]
    assert "____" in body["sentence"]
    assert body["sentence_id"] == 1


def test_course_answer_stores_question_provenance() -> None:
    """An answer records the question type, example shown, and time taken."""

    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice")

    response = client.post(
        "/api/v1/me/courses/eo/answer",
        json={
            "word": "saluton",
            "response": "y",
            "question_type": "type_word",
            "sentence_id": 42,
            "seconds": 3.0,
        },
        headers=_auth(token),
    )

    assert response.status_code == 204
    records, _ = postgres.load_learning("alice", "eo")
    question_id, _response, response_time, request_time, extra = records[-1]
    assert question_id == "saluton"
    assert extra == {"qt": "type_word", "si": 42}
    # `request_time` is derived from `seconds`, so it precedes the answer time.
    assert request_time is not None
    assert request_time < response_time


def test_course_answer_provenance_defaults() -> None:
    """Without a sentence or timing, only the question type is recorded."""

    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice")

    client.post(
        "/api/v1/me/courses/eo/answer",
        json={"word": "saluton", "response": "y"},
        headers=_auth(token),
    )

    records, _ = postgres.load_learning("alice", "eo")
    _question_id, _response, _response_time, request_time, extra = records[-1]
    assert extra == {"qt": "type_word"}  # Default type, no example shown.
    assert request_time is None


def test_learning_model_round_trips_question_type() -> None:
    """The `Learning` model surfaces `qt`, so the data export preserves it."""

    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice")
    client.post(
        "/api/v1/me/courses/eo/answer",
        json={"word": "saluton", "response": "y", "question_type": "type_word"},
        headers=_auth(token),
    )

    config = postgres.get_learn_config("alice", "eo")
    assert config is not None
    learning = Learning.from_config(
        Path(), LearnConfig(**config), "eo", "alice"
    )
    assert learning.process.records[-1].question_type == "type_word"


# Question types: server picks by config, knowledge level, and available data.


class _FakeQuestionData:
    """Stand-in data with no dictionaries (choice/connect then infeasible)."""

    def get_dictionaries(
        self,
        usage_configs: object,  # noqa: ARG002
    ) -> DictionaryCollection:
        return DictionaryCollection([])


def _add_due_word(
    course_id: str,
    word: str,
    responses: list[str],
    age: timedelta = timedelta(hours=2),
) -> None:
    """Add a learning word whose records make it due now, in the past."""

    base = datetime.now(UTC) - age
    records = [
        (word, response, base + timedelta(minutes=index), None, None)
        for index, response in enumerate(responses)
    ]
    postgres.save_learning("alice", course_id, "Esperanto", "eo", records, [])


def test_question_is_none_when_nothing_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no due words, the endpoint offers no review question."""

    monkeypatch.setattr(app_module, "get_data", lambda: _FakeQuestionData())
    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice")

    response = client.get(
        "/api/v1/me/courses/eo/question", headers=_auth(token)
    )

    assert response.status_code == 200
    assert response.json()["type"] is None


def test_question_uses_know_for_a_new_review_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A freshly-failed word (streak 0) is asked with the gentlest type."""

    monkeypatch.setattr(app_module, "get_data", lambda: _FakeQuestionData())
    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice")
    _add_due_word("eo", "saluton", ["n"])

    response = client.get(
        "/api/v1/me/courses/eo/question", headers=_auth(token)
    )

    body = response.json()
    assert body["type"] == "know"
    assert body["words"] == ["saluton"]


def test_question_types_config_restricts_the_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A course may limit itself to certain question types."""

    monkeypatch.setattr(app_module, "get_data", lambda: _FakeQuestionData())
    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice", scheme={"question_types": ["type_word"]})
    _add_due_word("eo", "saluton", ["n"])

    response = client.get(
        "/api/v1/me/courses/eo/question", headers=_auth(token)
    )

    body = response.json()
    assert body["type"] == "type_word"
    assert body["accepted"] == ["saluton"]


def test_question_falls_back_to_know_for_a_stale_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A word not answered for over two weeks is re-asked with `know`."""

    monkeypatch.setattr(app_module, "get_data", lambda: _FakeQuestionData())
    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice")
    # A streak of three would normally earn `type_word`.
    _add_due_word("eo", "saluton", ["y", "y", "y"], age=timedelta(weeks=3))

    response = client.get(
        "/api/v1/me/courses/eo/question", headers=_auth(token)
    )

    body = response.json()
    assert body["type"] == "know"
    assert body["words"] == ["saluton"]
    # The card's status context: the streak and when it was last answered.
    assert body["streak"] == 3
    last = datetime.fromisoformat(body["last_answer_time"])
    assert datetime.now(UTC) - last > timedelta(weeks=2)


def test_question_stale_fallback_needs_know_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without `know` among the course's types, staleness changes nothing."""

    monkeypatch.setattr(app_module, "get_data", lambda: _FakeQuestionData())
    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice", scheme={"question_types": ["type_word"]})
    _add_due_word("eo", "saluton", ["y", "y", "y"], age=timedelta(weeks=3))

    response = client.get(
        "/api/v1/me/courses/eo/question", headers=_auth(token)
    )

    assert response.json()["type"] == "type_word"


def test_question_accepts_simplified_spellings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typed answer may use the x-system or h-system spelling."""

    monkeypatch.setattr(app_module, "get_data", lambda: _FakeQuestionData())
    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice", scheme={"question_types": ["type_word"]})
    _add_due_word("eo", "anstataŭ", ["n"])

    response = client.get(
        "/api/v1/me/courses/eo/question", headers=_auth(token)
    )

    body = response.json()
    assert body["type"] == "type_word"
    assert body["accepted"] == ["anstataŭ", "anstataux", "anstatauh"]


def test_question_builds_a_choice_with_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Choice offers the right translation among distractors."""

    monkeypatch.setattr(app_module, "get_data", lambda: _FakeQuestionData())
    short = {"a": "A", "b": "B", "c": "C", "d": "D"}

    async def fake_short(
        word: str,
        language: object,  # noqa: ARG001
        dictionaries: object,  # noqa: ARG001
        base_languages: object,  # noqa: ARG001
    ) -> str | None:
        return short.get(word)

    monkeypatch.setattr(app_module, "_short_translation", fake_short)
    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice", scheme={"question_types": ["choice"]})
    for word in ["a", "b", "c", "d"]:
        _add_due_word("eo", word, ["n"])

    response = client.get(
        "/api/v1/me/courses/eo/question", headers=_auth(token)
    )

    body = response.json()
    assert body["type"] == "choice"
    assert len(body["options"]) == 4
    assert body["answer"] in body["options"]
    # The correct option is the target word's translation.
    assert body["answer"] == short[body["words"][0]]


def test_question_groups_words_into_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enough matchable low-knowledge words are grouped into one connect."""

    monkeypatch.setattr(app_module, "get_data", lambda: _FakeQuestionData())
    short = {"a": "A", "b": "B", "c": "C", "d": "D"}

    async def fake_short(
        word: str,
        language: object,  # noqa: ARG001
        dictionaries: object,  # noqa: ARG001
        base_languages: object,  # noqa: ARG001
    ) -> str | None:
        return short.get(word)

    monkeypatch.setattr(app_module, "_short_translation", fake_short)
    token = _register_and_login("alice", "alice@example.com")
    _make_course("alice")  # All types enabled.
    for word in ["a", "b", "c", "d"]:
        _add_due_word("eo", word, ["n"])

    response = client.get(
        "/api/v1/me/courses/eo/question", headers=_auth(token)
    )

    body = response.json()
    assert body["type"] == "connect"
    assert {pair["word"] for pair in body["pairs"]} == {"a", "b", "c", "d"}


def _create_uk_lexicon(token: str, selection: str) -> None:
    """Create a Ukrainian lexicon with the given selection strategy."""
    response = client.post(
        "/api/v1/me/lexicons",
        json={"language": "uk", "selection": selection},
        headers=_auth(token),
    )
    assert response.status_code == 201
    assert response.json()["lexicon_id"] == "uk"


def _next_words(
    token: str, session_id: str | None = None, lexicon_id: str = "uk"
) -> list[str]:
    """Fetch the next lexicon words to present."""
    params: dict[str, str] = {}
    if session_id is not None:
        params["session_id"] = session_id
    response = client.get(
        f"/api/v1/me/lexicons/{lexicon_id}/next",
        params=params,
        headers=_auth(token),
    )
    assert response.status_code == 200
    return [card["word"] for card in response.json()["words"]]


@pytest.mark.usefixtures("fake_uk_list")
def test_lexicon_session_records_a_session_row() -> None:
    """A checking session groups answers and writes one session row."""

    token = _register_and_login("alice", "alice@example.com")
    _create_uk_lexicon(token, "top")

    opened = client.post(
        "/api/v1/me/lexicons/uk/sessions", headers=_auth(token)
    )
    assert opened.status_code == 201
    session_id: str = opened.json()["session_id"]

    assert _next_words(token, session_id) == [_UK_WORDS[0]]
    answer = client.post(
        "/api/v1/me/lexicons/uk/answer",
        json={
            "word": _UK_WORDS[0],
            "response": "know",
            "session_id": session_id,
        },
        headers=_auth(token),
    )
    assert answer.status_code == 204
    # The session's working memory already knows the word was answered.
    assert _next_words(token, session_id) == [_UK_WORDS[1]]

    closed = client.post(
        f"/api/v1/me/lexicons/uk/sessions/{session_id}/close",
        headers=_auth(token),
    )
    assert closed.status_code == 204
    _records, sessions = postgres.load_lexicon("alice", "uk")
    assert len(sessions) == 1
    # Closing again is a safe no-op.
    client.post(
        f"/api/v1/me/lexicons/uk/sessions/{session_id}/close",
        headers=_auth(token),
    )
    assert len(postgres.load_lexicon("alice", "uk")[1]) == 1


@pytest.mark.usefixtures("fake_uk_list")
def test_lexicon_session_without_answers_leaves_no_row() -> None:
    """Opening and closing without answering writes no session row."""

    token = _register_and_login("alice", "alice@example.com")
    _create_uk_lexicon(token, "top")

    session_id = client.post(
        "/api/v1/me/lexicons/uk/sessions", headers=_auth(token)
    ).json()["session_id"]
    client.post(
        f"/api/v1/me/lexicons/uk/sessions/{session_id}/close",
        headers=_auth(token),
    )

    assert postgres.load_lexicon("alice", "uk")[1] == []


@pytest.mark.usefixtures("fake_uk_list")
def test_lexicon_session_unknown_id_reopens_transparently() -> None:
    """An identifier the server does not know still serves words."""

    token = _register_and_login("alice", "alice@example.com")
    _create_uk_lexicon(token, "top")

    assert _next_words(token, "unknown-session") == [_UK_WORDS[0]]


@pytest.mark.usefixtures("fake_uk_list")
def test_lexicon_session_detects_out_of_band_answers() -> None:
    """Answers bypassing the session are noticed via the freshness stamp."""

    token = _register_and_login("alice", "alice@example.com")
    _create_uk_lexicon(token, "top")
    session_id = client.post(
        "/api/v1/me/lexicons/uk/sessions", headers=_auth(token)
    ).json()["session_id"]
    assert _next_words(token, session_id) == [_UK_WORDS[0]]

    # The first word gets answered outside the session (another device).
    postgres.save_lexicon(
        "alice", "uk", "uk", [(_UK_WORDS[0], "K", datetime.now(UTC), None)], []
    )

    assert _next_words(token, session_id) == [_UK_WORDS[1]]


@pytest.mark.usefixtures("fake_uk_list")
def test_lexicon_session_serves_stratified_draws() -> None:
    """A stratified session draws untested words and never repeats answers."""

    token = _register_and_login("alice", "alice@example.com")
    _create_uk_lexicon(token, "stratified")
    session_id = client.post(
        "/api/v1/me/lexicons/uk/sessions", headers=_auth(token)
    ).json()["session_id"]

    seen: set[str] = set()
    for _ in range(10):
        words = _next_words(token, session_id)
        assert len(words) == 1
        word = words[0]
        assert word in _UK_WORDS
        assert word not in seen
        seen.add(word)
        assert (
            client.post(
                "/api/v1/me/lexicons/uk/answer",
                json={
                    "word": word,
                    "response": "dont",
                    "session_id": session_id,
                },
                headers=_auth(token),
            ).status_code
            == 204
        )


def _create_second_uk_lexicon(token: str) -> str:
    """Create a second stratified Ukrainian lexicon and return its id."""
    response = client.post(
        "/api/v1/me/lexicons",
        json={"language": "uk", "selection": "stratified"},
        headers=_auth(token),
    )
    assert response.status_code == 201
    return str(response.json()["lexicon_id"])


def test_lexicon_session_selector_ignores_sibling_answers(
    fake_uk_list: FrequencyList,
) -> None:
    """A fresh lexicon's selector is seeded from its own records only.

    Sibling answers drive skip decisions, but must not enter the selector's
    statistics: ingested answers count as the strategy's own draws, so
    bulk-ingesting them would let a fresh lexicon skip its coverage pass.
    """
    token = _register_and_login("alice", "alice@example.com")
    _create_uk_lexicon(token, "stratified")
    second_id: str = _create_second_uk_lexicon(token)
    sibling: list[str] = _UK_WORDS[10:15]
    postgres.save_lexicon(
        "alice",
        "uk",
        "uk",
        [(word, "K", datetime.now(UTC), None) for word in sibling],
        [],
    )

    session = LEXICON_SESSIONS.open(
        "alice", second_id, "uk", LexiconSelection.STRATIFIED, fake_uk_list
    )

    # Sibling answers still drive the skip decisions...
    assert sibling[0] in session.states
    # ...but the selector has no tested words in any stratum: every stratum
    # reports maximum uncertainty, so the coverage pass is still owed.
    assert isinstance(session.selector, StratifiedSelector)
    assert session.selector.theta_by_stratum() == [0.5] * 10


@pytest.mark.usefixtures("fake_uk_list")
def test_fresh_lexicon_runs_coverage_and_propagates_sibling_answers() -> None:
    """A fresh lexicon surveys sibling-answered strata via propagation.

    Words ranked 11-15 form the heaviest-mass stratum of the fake list, all
    answered in the sibling lexicon. The fresh lexicon's coverage pass must
    still draw that stratum: the drawn word is auto-answered from the recent
    sibling answer (never presented), which records the propagation in the
    fresh lexicon and marks the stratum tested.
    """
    token: str = _register_and_login("alice", "alice@example.com")
    _create_uk_lexicon(token, "stratified")
    second_id: str = _create_second_uk_lexicon(token)
    sibling: set[str] = set(_UK_WORDS[10:15])
    postgres.save_lexicon(
        "alice",
        "uk",
        "uk",
        [(word, "K", datetime.now(UTC), None) for word in sibling],
        [],
    )
    session_id: str = client.post(
        f"/api/v1/me/lexicons/{second_id}/sessions", headers=_auth(token)
    ).json()["session_id"]

    for _ in range(3):
        words = _next_words(token, session_id, lexicon_id=second_id)
        assert len(words) == 1
        word = words[0]
        # Recently answered in the sibling: propagated, never re-asked.
        assert word not in sibling
        assert (
            client.post(
                f"/api/v1/me/lexicons/{second_id}/answer",
                json={
                    "word": word,
                    "response": "not_a_word",
                    "session_id": session_id,
                },
                headers=_auth(token),
            ).status_code
            == 204
        )

    # Covering the sibling-answered stratum propagated an answer into this
    # lexicon instead of treating the stratum as already surveyed.
    assert postgres.get_answered_words("alice", second_id) & sibling


@pytest.mark.usefixtures("fake_languages")
def test_course_session_groups_answers_into_a_row() -> None:
    """A learning session groups answers into one `learn_sessions` row."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/courses", json={"language": "uk"}, headers=_auth(token)
    )
    opened = client.post(
        "/api/v1/me/courses/uk/sessions",
        json={"type": "repeat"},
        headers=_auth(token),
    )
    assert opened.status_code == 201
    session_id: str = opened.json()["session_id"]

    for word, response_code in (("хата", "y"), ("вода", "n")):
        answer = client.post(
            "/api/v1/me/courses/uk/answer",
            json={
                "word": word,
                "response": response_code,
                "session_id": session_id,
            },
            headers=_auth(token),
        )
        assert answer.status_code == 204

    closed = client.post(
        f"/api/v1/me/courses/uk/sessions/{session_id}/close",
        headers=_auth(token),
    )
    assert closed.status_code == 204

    records, sessions = postgres.load_learning("alice", "uk")
    assert len(records) == 2
    assert len(sessions) == 1
    session_type, start, end, actions = sessions[0]
    assert session_type == "repeat"
    assert actions == 2
    assert end
    assert start <= end


@pytest.mark.usefixtures("fake_languages")
def test_course_answer_updates_cached_schedule() -> None:
    """An answer through the cached course updates its stats in place."""

    token = _register_and_login("alice", "alice@example.com")
    client.post(
        "/api/v1/me/courses", json={"language": "uk"}, headers=_auth(token)
    )
    client.post(
        "/api/v1/me/courses/uk/answer",
        json={"word": "хата", "response": "n"},
        headers=_auth(token),
    )

    stats = client.get(
        "/api/v1/me/courses/uk/stats", headers=_auth(token)
    ).json()
    assert stats["answers"] == 1
    assert stats["actions"] == 1
