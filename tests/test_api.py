"""Tests for the HTTP API."""

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from emmio import postgres
from emmio.api import app as app_module
from emmio.api.app import app
from emmio.dictionary.core import DictionaryCollection
from emmio.language import Language
from emmio.learn.config import LearnConfig
from emmio.learn.core import Learning
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

    def __init__(self, languages: dict[str, dict]) -> None:
        self._languages = languages
        self.dictionaries = _FakeDictionaries()

    def get_frequency_list_languages(self) -> dict[str, dict]:
        return self._languages

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
        json={"translation_languages": ["en", "ru"], "precision_per_week": 20},
        headers=_auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "uk"
    assert body["translation_languages"] == ["en", "ru"]
    assert body["precision_per_week"] == 20

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
    assert config["precision_per_week"] == 20
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
        json={"precision_per_week": 10},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json()["translation_languages"] == ["en"]
    config = postgres.get_lexicon_config("alice", "uk")
    assert config is not None
    assert config["dictionaries"] == [  # Untouched.
        {"id": "google_translate", "from_language": "uk", "to_language": "en"}
    ]
    assert config["precision_per_week"] == 10


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


def _add_due_word(course_id: str, word: str, responses: list[str]) -> None:
    """Add a learning word whose records make it due now, in the past."""

    base = datetime.now(UTC) - timedelta(hours=2)
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
