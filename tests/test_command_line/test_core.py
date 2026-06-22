"""Command-line test core functionality.

This file contains no tests, but it's name should start with "test_" for
asserts to work correctly in Pytest.
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent
from typing import Any, cast
from unittest.mock import patch

import pytest

from emmio import postgres
from emmio.__main__ import main
from emmio.learn.config import LearningConfigType
from emmio.lexicon.config import LexiconConfigType
from emmio.lexicon.core import AnswerType, LexiconResponse
from emmio.user.config import UserConfigType

DictionaryConfigType = dict[str, str | bool]
ListConfigType = dict[str, str | bool]
SentencesConfigType = dict[str, str | list[str]]

LearningContentType = dict[str, list[dict[str, str]]]
LexiconContentType = dict[str, list[dict[str, str]]]

DEFAULT_DATA_DIRECTORY: Path = Path("__test_existing_data")
DEFAULT_USER_ID: str = "alice"
DEFAULT_USER_NAME: str = "Alice"

DICTIONARY_NB_EN: DictionaryConfigType = {
    "type": "file",
    "file_name": "nb_en.json",
    "name": "Norwegian Bokmål-English Dictionary",
    "from_language": "nb",
    "to_language": "en",
}
LIST_NB: ListConfigType = {
    "language": "nb",
    "file_format": "list",
    "path": "nb.txt",
    "type": "frequency_list",
    "is_stripped": False,
}


def check_main(
    capsys: pytest.CaptureFixture[str],
    temp_directory: Path = DEFAULT_DATA_DIRECTORY,
    temp_user_id: str = DEFAULT_USER_ID,
    user_commands: list[str] | None = None,
    expected_output: str | None = None,
) -> None:
    """Run Emmio and check output."""

    if user_commands is None:
        user_commands = []

    try:
        with (
            patch("builtins.input", side_effect=user_commands),
            patch(
                "sys.argv",
                [
                    "emmio",
                    "--user",
                    temp_user_id,
                    "--data",
                    temp_directory.absolute().as_posix(),
                    "--use-input",
                    "--interface",
                    "terminal",
                ],
            ),
        ):
            main()
            captured = capsys.readouterr()
            if expected_output:
                split_expected_output: list[str] = [
                    line.strip() for line in expected_output.splitlines()
                ]
                split_captured_output: list[str] = [
                    line.strip() for line in captured.out.splitlines()
                ]
                assert split_captured_output == split_expected_output

        assert Path(temp_directory).exists()
        for subdirectory in "dictionaries", "texts", "users":
            assert Path(temp_directory, subdirectory).exists()
        assert Path(temp_directory, "users", temp_user_id).exists()
        assert Path(
            temp_directory, "users", temp_user_id, "config.json"
        ).exists()
    finally:
        shutil.rmtree(temp_directory, ignore_errors=True)


HEADER: str = dedent(
    """
    Emmio
    Press <Enter> or print "learn" to start learning.
    Print "help" to see commands or "exit" to quit.
    """
).strip()


def _parse_time(value: str) -> datetime:
    """Parse ISO timestamp, assuming UTC when the time zone is missing."""

    time: datetime = datetime.fromisoformat(value)
    if time.tzinfo is None:
        time = time.replace(tzinfo=UTC)
    return time


def _store_learning(
    user_id: str,
    course_id: str,
    config: LearningConfigType,
    content: LearningContentType,
) -> None:
    """Store learning content in the test database."""

    records: list[postgres.LearnRecordRow] = []
    for record in content.get("records", []):
        extra: dict[str, Any] | None = (
            {"si": record["sentence_id"]} if record.get("sentence_id") else None
        )
        records.append(
            (
                record["question_id"],
                record["response"],
                _parse_time(record["time"]),
                (
                    _parse_time(record["request_time"])
                    if record.get("request_time")
                    else None
                ),
                extra,
            )
        )
    sessions: list[postgres.LearnSessionRow] = [
        (
            session["type"],
            _parse_time(session["start"]),
            (_parse_time(session["end"]) if session.get("end") else None),
            cast("int | None", session.get("actions")),
        )
        for session in content.get("sessions", [])
    ]
    # Store the course's configuration (the CLI reads it from the database),
    # then its records.
    postgres.store_learn_config(user_id, course_id, dict(config))
    postgres.save_learning(
        user_id,
        course_id,
        cast("str", config["name"]),
        cast("str", config["learning_language"]),
        records,
        sessions,
    )


def _store_lexicon(
    user_id: str,
    lexicon_id: str,
    config: LexiconConfigType,
    content: LexiconContentType,
) -> None:
    """Store lexicon content in the test database."""

    records: list[postgres.LexiconRecordRow] = []
    for record in content.get("records", []):
        extra: dict[str, Any] = {}
        if (answer_type := record.get("answer_type")) and (
            code := AnswerType(answer_type).to_code()
        ):
            extra["at"] = code
        if record.get("to_skip") is not None:
            extra["sk"] = record["to_skip"]
        records.append(
            (
                record["word"],
                LexiconResponse(record["response"]).to_code(),
                _parse_time(record["time"]),
                extra or None,
            )
        )
    sessions: list[postgres.LexiconSessionRow] = [
        (
            _parse_time(session["start"]),
            (_parse_time(session["end"]) if session.get("end") else None),
        )
        for session in content.get("sessions", [])
    ]
    # Store the lexicon's configuration (the CLI reads it from the database),
    # then its records.
    postgres.store_lexicon_config(user_id, lexicon_id, dict(config))
    postgres.save_lexicon(
        user_id, lexicon_id, cast("str", config["language"]), records, sessions
    )


def initialize(
    temp_directory: Path = DEFAULT_DATA_DIRECTORY,
    temp_user_id: str = DEFAULT_USER_ID,
    temp_user_name: str = DEFAULT_USER_NAME,
    # Artifacts.
    dictionaries_configuration: dict[str, DictionaryConfigType] | None = None,
    dictionaries: dict[str, str] | None = None,
    lists_configuration: dict[str, ListConfigType] | None = None,
    lists: dict[str, str] | None = None,
    sentences_configuration: dict[str, SentencesConfigType] | None = None,
    sentences: dict[str, str] | None = None,
    # User data.
    lexicons_configuration: dict[str, LexiconConfigType] | None = None,
    lexicons: dict[str, LexiconContentType] | None = None,
    learning_configuration: dict[str, LearningConfigType] | None = None,
    learnings: dict[str, LearningContentType] | None = None,
) -> None:
    """Initialize Emmio configuration directory."""

    for subdirectory in "lists", "dictionaries", "sentences":
        (temp_directory / subdirectory).mkdir(parents=True, exist_ok=True)
    temp_user_directory: Path = temp_directory / "users" / temp_user_id
    temp_user_directory.mkdir(parents=True, exist_ok=True)
    for subdirectory in "lexicon", "learn":
        (temp_user_directory / subdirectory).mkdir(parents=True, exist_ok=True)
    temp_user_config: Path = temp_user_directory / "config.json"

    # Configurate dictionaries.

    if dictionaries_configuration is None:
        dictionaries_configuration = {}
    with (temp_directory / "dictionaries" / "config.json").open(
        "w", encoding="utf-8"
    ) as output_file:
        json.dump(dictionaries_configuration, output_file)

    if dictionaries is not None:
        for file_name, content in dictionaries.items():
            with (temp_directory / "dictionaries" / file_name).open(
                "w", encoding="utf-8"
            ) as output_file:
                output_file.write(content)

    # Configurate lists.

    if lists_configuration is None:
        lists_configuration = {}
    with (temp_directory / "lists" / "config.json").open(
        "w", encoding="utf-8"
    ) as output_file:
        json.dump(lists_configuration, output_file)

    if lists is not None:
        for file_name, content in lists.items():
            with (temp_directory / "lists" / file_name).open(
                "w", encoding="utf-8"
            ) as output_file:
                output_file.write(content)

    # Configurate sentences.

    if sentences_configuration is None:
        sentences_configuration = {}
    with (temp_directory / "sentences" / "config.json").open(
        "w", encoding="utf-8"
    ) as output_file:
        json.dump(sentences_configuration, output_file)

    if sentences is not None:
        for file_name, content in sentences.items():
            with (temp_directory / "sentences" / file_name).open(
                "w", encoding="utf-8"
            ) as output_file:
                output_file.write(content)

    user_configuration: UserConfigType = {
        "name": temp_user_name,
        "learn": {},
        "lexicon": {},
        "read": {},
        "listen": {},
    }

    # The user must exist in the database before any data is stored for it.
    postgres.ensure_user(temp_user_id, temp_user_name)

    # Configurate lexicons.

    if lexicons_configuration is not None:
        user_configuration["lexicon"] = lexicons_configuration
    with temp_user_config.open("w", encoding="utf-8") as output_file:
        json.dump(user_configuration, output_file)

    if lexicons is not None and lexicons_configuration is not None:
        for file_name, lexicon_structure in lexicons.items():
            for lexicon_id, lexicon_config in lexicons_configuration.items():
                if lexicon_config["file_name"] == file_name:
                    _store_lexicon(
                        temp_user_id,
                        lexicon_id,
                        lexicon_config,
                        lexicon_structure,
                    )

    # Configurate learnings.

    if learning_configuration is not None:
        user_configuration["learn"] = learning_configuration
    with temp_user_config.open("w", encoding="utf-8") as output_file:
        json.dump(user_configuration, output_file)

    if learnings is not None and learning_configuration is not None:
        for file_name, learning_structure in learnings.items():
            for course_id, learning_config in learning_configuration.items():
                if learning_config["file_name"] == file_name:
                    _store_learning(
                        temp_user_id,
                        course_id,
                        learning_config,
                        learning_structure,
                    )
