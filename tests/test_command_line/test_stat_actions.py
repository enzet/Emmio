"""Test `stat actions` command."""

from pytest import CaptureFixture

from tests.test_command_line.test_core import HEADER, check_main, initialize


def test_stat_actions(capsys: CaptureFixture[str]) -> None:
    """Test simple `stat actions` command."""

    initialize()
    check_main(
        capsys,
        user_commands=["stat actions", "q"],
        expected_output=(
            HEADER
            + "\nLanguage Actions Average action time Approximated time\n\n"
        ),
    )
