"""Test `curate` command."""

import pytest

from emmio import postgres
from tests.test_command_line.test_core import check_main, initialize


def test_curate_votes_are_recorded(capsys: pytest.CaptureFixture[str]) -> None:
    """Answering two candidates records both votes with the right category."""

    initialize()
    list_id: int = postgres.create_curated_list(
        "de", "test_de_list", "Test German Curated"
    )
    postgres.add_curated_words(
        list_id, [("katze", 0, 0, "bootstrap"), ("hund", 0, 1, "bootstrap")]
    )

    check_main(
        capsys,
        user_commands=[
            "curate de test_de_list",  # Start curating.
            "w",  # "katze" is a real word.
            "n",  # "hund" is not a word.
            "exit",  # Quit Emmio.
        ],
    )

    words = {
        word: category
        for word, _, _, category, _, _ in postgres.get_curated_words(list_id)
    }
    assert words == {"katze": "W", "hund": "N"}


def test_curate_quit_records_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Answering "Quit" on the first candidate records no vote at all."""

    initialize()
    list_id: int = postgres.create_curated_list(
        "de", "test_de_list", "Test German Curated"
    )
    postgres.add_curated_words(list_id, [("katze", 0, 0, "bootstrap")])

    check_main(capsys, user_commands=["curate de test_de_list", "q", "exit"])

    words = postgres.get_curated_words(list_id)
    assert words[0][3] == "U"  # Category is unchanged: unknown.
    assert words[0][4] == 0  # No votes recorded.


def test_curate_skips_words_outside_the_alphabet(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A word with symbols outside the language's alphabet is never asked.

    It is auto-resolved as "not a word" and left untouched in the
    database (category `U`, no votes) — only `katze` is actually prompted,
    so a single `"w"` answer is enough to drain the whole list.
    """

    initialize()
    list_id: int = postgres.create_curated_list(
        "de", "test_de_list", "Test German Curated"
    )
    postgres.add_curated_words(
        list_id, [("日本語", 0, 0, "bootstrap"), ("katze", 0, 1, "bootstrap")]
    )

    check_main(capsys, user_commands=["curate de test_de_list", "w", "exit"])

    words = {
        word: (category, votes)
        for word, _, _, category, votes, _ in postgres.get_curated_words(
            list_id
        )
    }
    assert words["katze"] == ("W", 1)
    assert words["日本語"] == ("U", 0)


def test_curate_unknown_list_prints_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Curating a list that was never built prints a message, no crash."""

    initialize()
    check_main(capsys, user_commands=["curate de nonexistent_list", "exit"])
