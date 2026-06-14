"""Tests for the HTTP API."""

from fastapi.testclient import TestClient

from emmio import postgres
from emmio.api.app import app

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

client: TestClient = TestClient(app)


def test_list_users() -> None:
    """All users are listed."""

    postgres.ensure_user("alice", "Alice")
    postgres.ensure_user("bob", "Bob")

    response = client.get("/api/v1/users")

    assert response.status_code == 200
    assert {user["user_id"] for user in response.json()} == {"alice", "bob"}


def test_courses_are_scoped_by_user() -> None:
    """A user only sees their own courses."""

    postgres.ensure_user("alice", "Alice")
    postgres.ensure_user("bob", "Bob")
    # Saving with empty records still creates the (owned) course.
    postgres.save_learning("alice", "fr", "French", "fr", [], [])

    alice_courses = client.get("/api/v1/users/alice/courses").json()
    bob_courses = client.get("/api/v1/users/bob/courses").json()

    assert [course["course_id"] for course in alice_courses] == ["fr"]
    assert bob_courses == []


def test_lexicons_are_scoped_by_user() -> None:
    """A user only sees their own lexicons."""

    postgres.ensure_user("alice", "Alice")
    postgres.save_lexicon("alice", "de", "de", [], [])

    lexicons = client.get("/api/v1/users/alice/lexicons").json()

    assert [lexicon["lexicon_id"] for lexicon in lexicons] == ["de"]
    assert lexicons[0]["language"] == "de"


def test_unknown_user_returns_404() -> None:
    """Requesting data for a non-existent user returns 404."""

    response = client.get("/api/v1/users/ghost/courses")

    assert response.status_code == 404
