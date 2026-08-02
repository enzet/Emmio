"""Test `lexicon` command."""

import json

import pytest

from emmio import postgres
from tests.test_command_line.test_core import (
    DICTIONARY_NB_EN,
    HEADER,
    LIST_NB,
    check_main,
    initialize,
)


def test_existing_user_empty_data(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that existing user is loaded with empty data."""

    initialize(
        dictionaries_configuration={"nb_en": DICTIONARY_NB_EN},
        dictionaries={"nb_en.json": json.dumps({"hei": "hi"})},
        lists_configuration={"nb": LIST_NB},
        lists={"nb.txt": "hei 1"},
        lexicons_configuration={
            "nb": {
                "language": "nb",
                "file_name": "nb.json",
                "selection": "frequency",
                "frequency_list": {"id": "nb"},
                "dictionaries": [{"id": "nb_en"}],
            }
        },
        lexicons={
            "nb.json": {
                "records": [
                    {
                        "word": "hei",
                        "response": "know",
                        "time": "2000-01-01T00:00:00",
                    }
                ]
            }
        },
    )
    check_main(
        capsys,
        user_commands=[
            "lexicon",  # Start checking lexicon.
            "",  # Press "Show answer" button.
            "y",  # Say "yes" for "Do you know the word?"
            "q",  # Quit.
        ],
        expected_output=HEADER
        + """
Lexicon for Norwegian Bokmål
hei
Last response was: knows at least one meaning of the word.
<Show translation>
Norwegian Bokmål-English Dictionary
hei
hi
Do you know at least one meaning of this word?
[Y] Yes  [N] No  [C] Class  [S] Yes, skip  [X] Not to check  [Q] Quit
knows at least one meaning of the word
Precision: 0.00
Rate so far is: unknown
Words: 1
""",
    )


def test_not_to_check_records_curation_vote(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Not to check -> subgroup writes a real curation vote.

    The word is added to a freshly auto-created curated list (the same
    `promote_fallback_word` mechanism an ordinary raw-list fallback draw
    already uses) and voted on as the chosen subgroup, unifying with
    `emmio curate` instead of a separate mechanism.
    """

    initialize(
        lists_configuration={"nb": LIST_NB},
        lists={"nb.txt": "katt 5"},
        lexicons_configuration={
            "nb": {
                "language": "nb",
                "file_name": "nb.json",
                "selection": "frequency",
                "frequency_list": {"id": "nb"},
            }
        },
        lexicons={"nb.json": {"records": []}},
    )
    check_main(
        capsys,
        user_commands=[
            "lexicon",  # Start checking lexicon.
            "x",  # "Not to check".
            "p",  # "Proper noun".
            "q",  # Quit.
        ],
    )

    list_id = postgres.get_curated_list_id("nb", "nb")
    assert list_id is not None
    words = {
        word: category
        for word, _, _, category, _, _ in postgres.get_curated_words(list_id)
    }
    assert words == {"katt": "P"}
