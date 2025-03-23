"""Test `lexicon` command."""

import json
from textwrap import dedent

from pytest import CaptureFixture

from tests.test_command_line.test_core import (
    DICTIONARY_NB_EN,
    HEADER,
    LIST_NB,
    check_main,
    initialize,
)


def test_existing_user_empty_data(capsys: CaptureFixture[str]) -> None:
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
                "precision_per_week": 5,
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
        + dedent(
            """
            Lexicon for Norwegian Bokmål
            hei
            Last response was: knows at least one meaning of the word.
            <Show translation>
            Norwegian Bokmål-English Dictionary
            hei
            hi
            Do you know at least one meaning of this word?
            [Y] Yes  [N] No  [B] Proper  [S] Yes, skip  [-] Not a word  [Q] Quit
            knows at least one meaning of the word
            Precision: 0.00
            Rate so far is: unknown
            Words: 1
            """
        ),
    )
