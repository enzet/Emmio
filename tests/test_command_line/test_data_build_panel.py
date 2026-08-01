"""Test `data build-panel` command."""

import pytest

from emmio import postgres
from tests.test_command_line.test_core import check_main, initialize


def test_build_panel_from_opensubtitles_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A properly named `_opensubtitles_` file is discovered and curated."""

    initialize(
        lists={
            "de_opensubtitles_2024.txt": (
                "ich 100 0.01\nkatze 3 1.00\nhund 5 0.20\n"
            )
        }
    )

    check_main(
        capsys,
        user_commands=[
            "data build-panel opensubtitles de --year 2024 --n-c 2",
            "exit",
        ],
    )

    list_id = postgres.get_curated_list_id("de", "de_opensubtitles_2024")
    assert list_id is not None
    words = {word for word, *_ in postgres.get_curated_words(list_id)}
    assert words == {"ich", "katze", "hund"}


def test_build_panel_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    """Running it twice does not duplicate or reset curated words."""

    for _ in range(2):
        # `check_main` tears the temp directory down after each call, so
        # the source file has to be recreated for both runs.
        initialize(
            lists={"de_opensubtitles_2024.txt": "ich 100 0.01\nkatze 3 1.00\n"}
        )
        check_main(
            capsys,
            user_commands=[
                "data build-panel opensubtitles de --year 2024",
                "exit",
            ],
        )

    list_id = postgres.get_curated_list_id("de", "de_opensubtitles_2024")
    assert list_id is not None
    assert len(postgres.get_curated_words(list_id)) == 2


def test_build_panel_tops_up_to_a_larger_target(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bigger `--n-c` fills a stratum up to the new target, not past it.

    All five words are forced into one stratum (`--n-strata 1`) so `--n-c`
    below the stratum size actually leaves some words undrawn.
    """

    all_words = {"ich", "katze", "hund", "maus", "vogel"}
    lists = {
        "de_opensubtitles_2024.txt": (
            "ich 100 0.01\nkatze 3 1.00\nhund 5 0.20\n"
            "maus 4 0.10\nvogel 2 0.05\n"
        )
    }

    # `check_main` tears the temp directory down after each call, so the
    # source file has to be recreated before every run.
    initialize(lists=lists)
    check_main(
        capsys,
        user_commands=[
            "data build-panel opensubtitles de --year 2024 --n-strata 1 "
            "--n-c 2",
            "exit",
        ],
    )
    list_id = postgres.get_curated_list_id("de", "de_opensubtitles_2024")
    assert list_id is not None
    assert len(postgres.get_curated_words(list_id)) == 2

    initialize(lists=lists)
    check_main(
        capsys,
        user_commands=[
            "data build-panel opensubtitles de --year 2024 --n-strata 1 "
            "--n-c 3",
            "exit",
        ],
    )
    words = {word for word, *_ in postgres.get_curated_words(list_id)}
    assert len(words) == 3
    assert words <= all_words

    # A larger target than the stratum holds: capped at the stratum size.
    initialize(lists=lists)
    check_main(
        capsys,
        user_commands=[
            "data build-panel opensubtitles de --year 2024 --n-strata 1 "
            "--n-c 100",
            "exit",
        ],
    )
    words = {word for word, *_ in postgres.get_curated_words(list_id)}
    assert words == all_words

    # A smaller target afterwards must not remove anything already curated.
    initialize(lists=lists)
    check_main(
        capsys,
        user_commands=[
            "data build-panel opensubtitles de --year 2024 --n-strata 1 "
            "--n-c 1",
            "exit",
        ],
    )
    words = {word for word, *_ in postgres.get_curated_words(list_id)}
    assert words == all_words


def test_build_panel_missing_file_prints_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No matching file: a clear message, not a crash."""

    initialize()

    check_main(
        capsys,
        user_commands=["data build-panel opensubtitles de --year 2024", "exit"],
    )

    assert postgres.get_curated_list_id("de", "de_opensubtitles_2024") is None
