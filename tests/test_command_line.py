"""Test the command line interface."""

import json
from pathlib import Path
import shutil
from typing import Callable
from unittest.mock import patch

from pytest import CaptureFixture
from emmio.__main__ import main


def initialize(
    temp_directory: Path,
    temp_user_id: str = "alice",
    temp_user_name: str = "Alice",
    dictionaries_configuration: dict | None = None,
    dictionaries: dict[str, str] | None = None,
    lists_configuration: dict | None = None,
    lists: dict[str, str] | None = None,
    lexicons_configuration: dict | None = None,
    lexicons: dict[str, dict] | None = None,
) -> None:
    """Initialize Emmio configuration directory."""

    for subdirectory in (
        "lists",
        "dictionaries",
    ):
        (temp_directory / subdirectory).mkdir(parents=True, exist_ok=True)
    temp_user_directory: Path = temp_directory / "users" / temp_user_id
    temp_user_directory.mkdir(parents=True, exist_ok=True)
    for subdirectory in "lexicon", "learn":
        (temp_user_directory / subdirectory).mkdir(parents=True, exist_ok=True)
    temp_user_config: Path = temp_user_directory / "config.json"

    # Configurate dictionaries.

    if dictionaries_configuration is not None:
        with open(
            temp_directory / "dictionaries" / "config.json", "w"
        ) as output_file:
            json.dump(dictionaries_configuration, output_file)

    if dictionaries is not None:
        for file_name, content in dictionaries.items():
            with open(
                temp_directory / "dictionaries" / file_name, "w"
            ) as output_file:
                output_file.write(content)

    # Configurate lists.

    if lists_configuration is not None:
        with open(temp_directory / "lists" / "config.json", "w") as output_file:
            json.dump(lists_configuration, output_file)

    if lists is not None:
        for file_name, content in lists.items():
            with open(temp_directory / "lists" / file_name, "w") as output_file:
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
    with open(temp_user_config, "w") as output_file:
        json.dump(user_configuration, output_file)

    if lexicons is not None:
        for file_name, lexicon_structure in lexicons.items():
            with open(
                temp_user_directory / "lexicon" / file_name, "w"
            ) as output_file:
                json.dump(lexicon_structure, output_file)


def check_main(
    capsys: Callable[[], CaptureFixture],
    temp_directory: Path,
    temp_user_id: str,
    user_commands: list[str],
    expected_output: list[str],
) -> None:
    """Run Emmio and check output."""

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
                ],
            ),
        ):
            main()
            captured: CaptureFixture = capsys.readouterr()
            for text in expected_output:
                assert text in captured.out

        assert Path(temp_directory).exists()
        for subdirectory in "dictionaries", "sentences", "texts", "users":
            assert Path(temp_directory, subdirectory).exists()
        assert Path(temp_directory, "users", temp_user_id).exists()
        assert Path(
            temp_directory, "users", temp_user_id, "config.json"
        ).exists()
    finally:
        shutil.rmtree(temp_directory, ignore_errors=True)


def test_new_user_empty_data(capsys: Callable[[], CaptureFixture]) -> None:
    """Test that a new user is created with empty data."""

    check_main(
        capsys,
        temp_directory=Path("__test_empty_data"),
        temp_user_id="alice",
        user_commands=["y", "Alice", "q"],
        expected_output=[
            "Emmio",
            f"User `alice` with name `Alice` created.",
        ],
    )


def test_existing_user_empty_data(capsys: Callable[[], CaptureFixture]) -> None:
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
        expected_output=[
            "Emmio",
        ],
    )
