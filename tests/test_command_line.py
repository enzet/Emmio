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
        temp_directory.mkdir(parents=True, exist_ok=True)
        temp_user_id: str = "alice"
        temp_user_directory: Path = temp_directory / "users" / temp_user_id
        temp_user_directory.mkdir(parents=True, exist_ok=True)
        temp_user_config: Path = temp_user_directory / "config.json"

        structure: dict = {
            "name": "Alice",
            "learn": {},
            "lexicon": {},
            "read": {},
            "listen": {},
        }

        with open(temp_user_config, "w") as output_file:
            json.dump(structure, output_file)

        with patch("builtins.input", side_effect=["q"]):
            with patch(
                "sys.argv",
                [
                    "emmio",
                    "--user",
                    temp_user_id,
                    "--data",
                    temp_directory.absolute().as_posix(),
                ],
            ):
                main()
                captured: CaptureFixture = capsys.readouterr()
                assert "Emmio" in captured.out
    finally:
        shutil.rmtree(temp_directory, ignore_errors=True)
