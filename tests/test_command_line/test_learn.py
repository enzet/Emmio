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
        dictionaries={
            "nb_en.json": json.dumps(
                {
                    "ja": "yes",
                    "hei": "hi",
                    "hva": "what",
                }
            )
        },
        lists_configuration={
            "nb": LIST_NB,
        },
        lists={"nb.txt": "ja 4\nhei 2\nhva 1"},
        learning_configuration={
            "nb": {
                "name": "Norwegian Bokmål",
                "learning_language": "nb",
                "base_languages": ["en"],
                "file_name": "nb.json",
                "dictionaries": [{"id": "nb_en"}],
                "scheme": {
                    "new_question": {
                        "pick_from": [{"id": "nb"}],
                    }
                },
            },
        },
        learnings={
            "nb.json": {
                "records": [
                    {
                        "question_id": "hei",
                        "response": "y",
                        "time": "2000-01-01T00:00:00",
                    },
                ],
            },
        },
    )
    check_main(
        capsys,
        user_commands=[
            "learn",  # Start learning process.
            "",  # Show translation.
            "ja",  # Answer "ja".
            "",  # Next question.
            "",  # Show translation.
            "hva",  # Answer "hva".
            "",  # Next question.
            "n",  # Answer "no" to "Continue?".
            "q",  # Quit.
        ],
        expected_output=HEADER
        + dedent(
            """
            Learn new words for Norwegian Bokmål
            New question.
            yes
            ja
            yes
            New question.
            what
            hva
            what
            2 actions made
            All new words added
            Continue?
            [Y] Yes  [N] No
            """
        ),
    )
