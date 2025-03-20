"""Test `plot lexicon` command."""

from pytest import CaptureFixture

from tests.test_command_line.core import HEADER, check_main, initialize


def test_plot_lexicon(capsys: CaptureFixture[str]) -> None:
    """Test `plot lexicon` command."""

    initialize()
    check_main(
        capsys,
        user_commands=["plot lexicon --svg", "q"],
        expected_output=HEADER,
    )
