"""Tests for the HTTP API."""

from fastapi.testclient import TestClient

from emmio import postgres
from emmio.api.app import app

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

client: TestClient = TestClient(app)


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
