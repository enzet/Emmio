"""Test `curate` command."""

import pytest

from emmio import postgres
from tests.test_command_line.test_core import check_main, initialize


def test_curate_votes_are_recorded(capsys: pytest.CaptureFixture[str]) -> None:
    """Answering four candidates records all with the right category."""

    initialize()
    list_id: int = postgres.create_curated_list(
        "de", "test_de_list", "Test German Curated"
    )
    postgres.add_curated_words(
        list_id,
        [
            ("katze", 0, 0, "bootstrap"),
            ("hund", 0, 1, "bootstrap"),
            ("nimmersatt", 0, 2, "bootstrap"),
            ("weekend", 0, 3, "bootstrap"),
        ],
    )

    check_main(
        capsys,
        user_commands=[
            "curate de test_de_list",  # Start curating.
            "w",  # "katze" is a real word (group 1: to check).
            "n",  # "hund" is not a word (group 2).
            "r",  # "nimmersatt" is real, but rare/slang/retro (group 2).
            "f",  # "weekend" is a foreign word (group 2).
            "exit",  # Quit Emmio.
        ],
    )

    words = {
        word: category
        for word, _, _, category, _, _ in postgres.get_curated_words(list_id)
    }
    assert words == {
        "katze": "W",
        "hund": "N",
        "nimmersatt": "R",
        "weekend": "F",
    }


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


def test_curate_import_lexicon_history(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--from-lexicon-history` votes using past `emmio lexicon` answers.

    Covers the full mapping (`know`/`dont` -> W, `dont_but_proper_noun_too`
    -> P, `not_a_word` -> N — both response types are legacy-only, no
    longer produced by `ask`, but old records using them still import),
    plus three exclusions: `know_or_not_a_word` is too ambiguous to
    import, a word with no lexicon history at all is left alone, and a
    propagated/assumed answer (not a genuine user answer) does not count
    as history either. A word already voted on by this curator is never
    touched, even though its own history disagrees.
    """

    initialize(
        lexicons_configuration={
            "de": {
                "language": "de",
                "file_name": "de.json",
                "selection": "frequency",
            }
        },
        lexicons={
            "de.json": {
                "records": [
                    {
                        "word": "katze",
                        "response": "know",
                        "time": "2020-01-01T00:00:00",
                    },
                    {
                        "word": "hund",
                        "response": "dont",
                        "time": "2020-01-01T00:00:00",
                    },
                    {
                        "word": "fuchs",
                        "response": "dont_but_proper_noun_too",
                        "time": "2020-01-01T00:00:00",
                    },
                    {
                        "word": "maus",
                        "response": "not_a_word",
                        "time": "2020-01-01T00:00:00",
                    },
                    {
                        "word": "bar",
                        "response": "know_or_not_a_word",
                        "time": "2020-01-01T00:00:00",
                    },
                    {
                        "word": "adler",
                        "response": "not_a_word",
                        "time": "2020-01-01T00:00:00",
                        "answer_type": "assume_not_a_word",
                    },
                    {
                        "word": "eule",
                        "response": "know",
                        "time": "2020-01-01T00:00:00",
                    },
                ]
            }
        },
    )
    list_id: int = postgres.create_curated_list(
        "de", "test_de_list", "Test German Curated"
    )
    panel_words: list[str] = [
        "katze",
        "hund",
        "fuchs",
        "maus",
        "bar",
        "adler",
        "eule",
        "wolf",
    ]
    postgres.add_curated_words(
        list_id,
        [
            (word, 0, index, "bootstrap")
            for index, word in enumerate(panel_words)
        ],
    )
    # Pre-existing vote: must survive the import untouched, even though
    # `eule`'s history above says `know`.
    postgres.record_curation_vote(list_id, "eule", "P", "alice")

    check_main(
        capsys,
        user_commands=["curate de test_de_list --from-lexicon-history", "exit"],
    )

    words = {
        word: category
        for word, _, _, category, _, _ in postgres.get_curated_words(list_id)
    }
    assert words == {
        "katze": "W",
        "hund": "W",
        "fuchs": "P",  # "Dont but proper noun too" imports as proper noun.
        "maus": "N",
        "bar": "U",  # Ambiguous response: left uncategorized.
        "adler": "U",  # Only a non-user-answer record: no real history.
        "eule": "P",  # Already voted on: untouched.
        "wolf": "U",  # No history at all.
    }


def test_curate_unknown_list_prints_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Curating a list that was never built prints a message, no crash."""

    initialize()
    check_main(capsys, user_commands=["curate de nonexistent_list", "exit"])
