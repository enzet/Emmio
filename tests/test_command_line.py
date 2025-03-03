"""Test the command line interface."""

import json
from pathlib import Path
import shutil
from typing import Callable
from unittest.mock import patch

from pytest import CaptureFixture
from emmio.__main__ import main


def test_new_user_empty_data(capsys: Callable[[], CaptureFixture]) -> None:
    """Test that a new user is created with empty data."""

    temp_directory: Path = Path("__test_empty_data")
    temp_user_id: str = "alice"

    shutil.rmtree(temp_directory, ignore_errors=True)

    try:
        with patch("builtins.input", side_effect=["y", "Alice", "q"]):
            with patch(
                "sys.argv",
                [
                    "emmio",
                    "--user",
                    temp_user_id,
                    "--data",
                    temp_directory.absolute().as_posix(),
                    "--use-input",
                ],
            ):
                main()
                captured: CaptureFixture = capsys.readouterr()
                assert "Emmio" in captured.out
                assert (
                    f"User `{temp_user_id}` with name `Alice` created."
                    in captured.out
                )

        assert Path(temp_directory).exists()
        for subdirectory in "dictionaries", "sentences", "texts", "users":
            assert Path(temp_directory, subdirectory).exists()
        assert Path(temp_directory, "users", temp_user_id).exists()
        assert Path(
            temp_directory, "users", temp_user_id, "config.json"
        ).exists()
    finally:
        shutil.rmtree(temp_directory, ignore_errors=True)


def test_existing_user_empty_data(capsys: Callable[[], CaptureFixture]) -> None:
    """Test that existing user is loaded with empty data."""

    try:
        temp_directory: Path = Path("__test_existing_data")
        for subdirectory in (
            "lists",
            "dictionaries",
        ):
            (temp_directory / subdirectory).mkdir(parents=True, exist_ok=True)
        temp_user_id: str = "alice"
        temp_user_directory: Path = temp_directory / "users" / temp_user_id
        temp_user_directory.mkdir(parents=True, exist_ok=True)
        for subdirectory in "lexicon", "learn":
            (temp_user_directory / subdirectory).mkdir(
                parents=True, exist_ok=True
            )
        temp_user_config: Path = temp_user_directory / "config.json"

        # Configurate dictionaries.

        dictionaries_configuration: dict = {
            "nb_en": {
                "type": "file",
                "file_name": "nb_en.json",
                "name": "Norwegian Bokmål-English Dictionary",
                "from_language": "nb",
                "to_language": "en",
            }
        }
        with open(
            temp_directory / "dictionaries" / "config.json", "w"
        ) as output_file:
            json.dump(dictionaries_configuration, output_file)

        with open(
            temp_directory / "dictionaries" / "nb_en.json", "w"
        ) as output_file:
            json.dump({"hei": "hi"}, output_file)

        # Configurate lists.

        lists_configuration: dict = {
            "nb": {
                "language": "nb",
                "file_format": "list",
                "path": "nb.txt",
                "type": "frequency_list",
                "is_stripped": False,
            },
        }
        with open(temp_directory / "lists" / "config.json", "w") as output_file:
            json.dump(lists_configuration, output_file)

        with open(temp_directory / "lists" / "nb.txt", "w") as output_file:
            output_file.write("hei 1")

        # Configurate user.

        user_config_structure: dict = {
            "name": "Alice",
            "learn": {},
            "lexicon": {
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
            "read": {},
            "listen": {},
        }
        with open(temp_user_config, "w") as output_file:
            json.dump(user_config_structure, output_file)

        lexicon_nb_structure: dict = {
            "records": [
                {
                    "word": "hei",
                    "response": "know",
                    "time": "2000-01-01T00:00:00",
                },
            ],
        }
        with open(
            temp_user_directory / "lexicon" / "nb.json", "w"
        ) as output_file:
            json.dump(lexicon_nb_structure, output_file)

        with patch(
            "builtins.input",
            side_effect=[
                "lexicon",  # Start checking lexicon.
                "",  # Press "Show answer" button.
                "y",  # Say "yes" for "Do you know the word?"
                "q",  # Quit.
            ],
        ):
            with patch(
                "sys.argv",
                [
                    "emmio",
                    "--user",
                    temp_user_id,
                    "--data",
                    temp_directory.absolute().as_posix(),
                    "--use-input",
                ],
            ):
                main()
                captured: CaptureFixture = capsys.readouterr()
                assert "Emmio" in captured.out
                print(captured.out)
    finally:
        shutil.rmtree(temp_directory, ignore_errors=True)
