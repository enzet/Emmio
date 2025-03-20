"""Test `lexicon` command."""

import json
from pathlib import Path
from textwrap import dedent

from pytest import CaptureFixture

from tests.test_command_line.core import HEADER, check_main, initialize


def test_existing_user_empty_data(capsys: CaptureFixture[str]) -> None:
    """Test that existing user is loaded with empty data."""

    temp_directory: Path = Path("__test_existing_data")
    temp_user_id: str = "alice"
    initialize(
        temp_directory=temp_directory,
        temp_user_id=temp_user_id,
        dictionaries_configuration={
            "nb_en": {
                "type": "file",
                "file_name": "nb_en.json",
                "name": "Norwegian Bokmål-English Dictionary",
                "from_language": "nb",
                "to_language": "en",
            }
        },
        dictionaries={"nb_en.json": json.dumps({"hei": "hi"})},
        lists_configuration={
            "nb": {
                "language": "nb",
                "file_format": "list",
                "path": "nb.txt",
                "type": "frequency_list",
                "is_stripped": False,
            },
        },
        lists={"nb.txt": "hei 1"},
        lexicons_configuration={
            "nb": {
                "language": "nb",
                "file_name": "nb.json",
                "selection": "frequency",
                "frequency_list": {"id": "nb"},
                "precision_per_week": 5,
                "dictionaries": [
                    {"id": "nb_en"},
                ],
            },
        },
        lexicons={
            "nb.json": {
                "records": [
                    {
                        "word": "hei",
                        "response": "know",
                        "time": "2000-01-01T00:00:00",
                    },
                ],
            },
        },
    )
    check_main(
        capsys,
        temp_directory=temp_directory,
        temp_user_id=temp_user_id,
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
