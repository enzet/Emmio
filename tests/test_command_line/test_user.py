"""Test user creation."""

from pathlib import Path

from pytest import CaptureFixture

from tests.test_command_line.test_core import HEADER, check_main


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
