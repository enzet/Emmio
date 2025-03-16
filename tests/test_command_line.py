"""Test the command line interface."""

import json
import shutil
from pathlib import Path
from textwrap import dedent
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

    if dictionaries_configuration is None:
        dictionaries_configuration = {}
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
    capsys: CaptureFixture[str],
    temp_directory: Path,
    temp_user_id: str,
    user_commands: list[str],
    expected_output: str | None = None,
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


def test_new_user_empty_data(capsys: CaptureFixture[str]) -> None:
    """Test that a new user is created with empty data."""

    check_main(
        capsys,
        temp_directory=Path("__test_empty_data"),
        temp_user_id="alice",
        user_commands=[
            "y",  # Say "yes" for "Do you want to create new user?"
            "Alice",  # Enter user name.
            "q",  # Quit.
        ],
        expected_output=(
            "User with id `alice` does not exist. Do you want to create new "
            "user?\n"
            "[Y] Yes  [N] No\n"
            "User `alice` with name `Alice` created.\n"
        )
        + HEADER,
    )


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


def test_plot_lexicon(capsys: CaptureFixture[str]) -> None:
    """Test `plot lexicon` command."""

    temp_directory: Path = Path("__test_existing_data")
    temp_user_id: str = "alice"
    initialize(
        temp_directory=temp_directory,
        temp_user_id=temp_user_id,
    )
    check_main(
        capsys,
        temp_directory=temp_directory,
        temp_user_id=temp_user_id,
        user_commands=["plot lexicon --svg", "q"],
        expected_output=HEADER,
    )


def test_stat_actions(capsys: CaptureFixture[str]) -> None:
    """Test `stat actions` command."""

    temp_directory: Path = Path("__test_existing_data")
    temp_user_id: str = "alice"
    initialize(
        temp_directory=temp_directory,
        temp_user_id=temp_user_id,
    )
    check_main(
        capsys,
        temp_directory=temp_directory,
        temp_user_id=temp_user_id,
        user_commands=["stat actions", "q"],
        expected_output=(
            HEADER
            + "\nLanguage Actions Average action time Approximated time\n\n"
        ),
    )
