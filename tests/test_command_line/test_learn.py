"""Test `learn` command."""

import json
from textwrap import dedent

from pytest import CaptureFixture

from tests.test_command_line.test_core import (
    DICTIONARY_NB_EN,
    HEADER,
    LIST_NB,
    LearningConfigType,
    LearningContentType,
    check_main,
    initialize,
)

DICTIONARY_NB_EN_CONTENT: str = json.dumps(
    {"ja": "yes", "hei": "hi", "hva": "what"}
)
LIST_NB_CONTENT: str = dedent(
    """
    ja 4
    hei 2
    hva 1
    """
)
LEARNING_NB: LearningConfigType = {
    "name": "Norwegian Bokmål",
    "learning_language": "nb",
    "base_languages": ["en"],
    "file_name": "nb.json",
    "dictionaries": [{"id": "nb_en"}],
    "scheme": {"new_question": {"pick_from": [{"id": "nb"}]}},
}
LEARNING_NB_CONTENT: LearningContentType = {
    "records": [
        {"question_id": "hei", "response": "y", "time": "2000-01-01T00:00:00"}
    ]
}


def test_learn(capsys: CaptureFixture[str]) -> None:
    """Test simplest `learn` command."""

    initialize(
        dictionaries_configuration={"nb_en": DICTIONARY_NB_EN},
        dictionaries={"nb_en.json": DICTIONARY_NB_EN_CONTENT},
        lists_configuration={"nb": LIST_NB},
        lists={"nb.txt": LIST_NB_CONTENT},
        learning_configuration={"nb": LEARNING_NB},
        learnings={"nb.json": LEARNING_NB_CONTENT},
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


def test_learn_with_sentences(capsys: CaptureFixture[str]) -> None:
    """Test `learn` command with sentences."""

    initialize(
        dictionaries_configuration={"nb_en": DICTIONARY_NB_EN},
        dictionaries={"nb_en.json": DICTIONARY_NB_EN_CONTENT},
        sentences_configuration={
            "nb_en": {
                "file_name": "nb_en.txt",
                "name": "Norwegian Bokmål to English",
                "language_1": "nb",
                "language_2": "en",
            }
        },
        sentences={
            "nb_en.txt": dedent(
                """
                ja, Maria
                yes, Maria
                hva? ja!
                what? yes!
                hei, Maria, ja
                hi, Maria, yes
                """
            ).strip()
        },
        lists_configuration={"nb": LIST_NB},
        lists={"nb.txt": LIST_NB_CONTENT},
        learning_configuration={
            "nb": {
                "name": "Norwegian Bokmål",
                "learning_language": "nb",
                "base_languages": ["en"],
                "file_name": "nb.json",
                "dictionaries": [{"id": "nb_en"}],
                "scheme": {"new_question": {"pick_from": [{"id": "nb"}]}},
                "sentences": [{"id": "nb_en"}],
            }
        },
        learnings={"nb.json": LEARNING_NB_CONTENT},
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
            hei, Maria, __
            hi, Maria, yes
            __, Maria
            yes, Maria
            ja
            yes
            New question.
            what
            ___? ja!
            <Reveal translations>
            what? yes!
            hva
            what
            2 actions made
            All new words added
            Continue?
            [Y] Yes  [N] No
            """
        ),
    )
