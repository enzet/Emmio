"""Command-line test core functionality."""

import json
import shutil
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from pytest import CaptureFixture

from emmio.__main__ import main

DEFAULT_DATA_DIRECTORY: Path = Path("__test_existing_data")
DEFAULT_USER_ID: str = "alice"
DEFAULT_USER_NAME: str = "Alice"


def check_main(
    capsys: CaptureFixture[str],
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
                split_expected_output: list[str] = expected_output.splitlines()
                split_captured_output: list[str] = captured.out.splitlines()
                for expected_line, actual_line in zip(
                    split_expected_output, split_captured_output
                ):
                    assert expected_line.rstrip() == actual_line.rstrip()
                assert len(split_expected_output) == len(split_captured_output)

        assert Path(temp_directory).exists()
        for subdirectory in "dictionaries", "sentences", "texts", "users":
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


def initialize(
    temp_directory: Path = DEFAULT_DATA_DIRECTORY,
    temp_user_id: str = DEFAULT_USER_ID,
    temp_user_name: str = DEFAULT_USER_NAME,
    dictionaries_configuration: dict | None = None,
    dictionaries: dict[str, str] | None = None,
    lists_configuration: dict | None = None,
    lists: dict[str, str] | None = None,
    lexicons_configuration: dict | None = None,
    lexicons: dict[str, dict] | None = None,
) -> None:
    """Initialize Emmio configuration directory."""

    for subdirectory in "lists", "dictionaries":
        (temp_directory / subdirectory).mkdir(parents=True, exist_ok=True)
    temp_user_directory: Path = temp_directory / "users" / temp_user_id
    temp_user_directory.mkdir(parents=True, exist_ok=True)
    for subdirectory in "lexicon", "learn":
        (temp_user_directory / subdirectory).mkdir(parents=True, exist_ok=True)
    temp_user_config: Path = temp_user_directory / "config.json"

    # Configurate dictionaries.

    if dictionaries_configuration is None:
        dictionaries_configuration = {}
    with open(
        temp_directory / "dictionaries" / "config.json",
        "w",
        encoding="utf-8",
    ) as output_file:
        json.dump(dictionaries_configuration, output_file)

    if dictionaries is not None:
        for file_name, content in dictionaries.items():
            with open(
                temp_directory / "dictionaries" / file_name,
                "w",
                encoding="utf-8",
            ) as output_file:
                output_file.write(content)

    # Configurate lists.

    if lists_configuration is not None:
        with open(
            temp_directory / "lists" / "config.json",
            "w",
            encoding="utf-8",
        ) as output_file:
            json.dump(lists_configuration, output_file)

    if lists is not None:
        for file_name, content in lists.items():
            with open(
                temp_directory / "lists" / file_name,
                "w",
                encoding="utf-8",
            ) as output_file:
                output_file.write(content)

    # Configurate user.

    user_configuration: dict = {
        "name": temp_user_name,
        "learn": {},
        "lexicon": {},
        "read": {},
        "listen": {},
    }
    if lexicons_configuration is not None:
        user_configuration["lexicon"] = lexicons_configuration
    with open(temp_user_config, "w", encoding="utf-8") as output_file:
        json.dump(user_configuration, output_file)

    if lexicons is not None:
        for file_name, lexicon_structure in lexicons.items():
            with open(
                temp_user_directory / "lexicon" / file_name,
                "w",
                encoding="utf-8",
            ) as output_file:
                json.dump(lexicon_structure, output_file)
