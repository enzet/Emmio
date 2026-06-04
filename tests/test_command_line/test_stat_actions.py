"""Test `stat actions` command."""

import pytest

from tests.test_command_line.test_core import HEADER, check_main, initialize


def test_stat_actions(capsys: pytest.CaptureFixture[str]) -> None:
    """Test simplest possible `stat actions` command."""

    initialize()
    check_main(
        capsys,
        user_commands=["stat actions", "q"],
        expected_output=(
            HEADER
            + "\nLanguage Actions Average action time Approximated time\n\n"
        ),
    )
