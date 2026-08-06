"""Test `data build-partial` command.

Only the "no such list" error path is exercised here: the happy path pulls
from the full Kaikki/Tatoeba data (network downloads on a cold cache, see
`emmio.dictionary.data.DictionaryData._start_kaikki_download` and
`emmio.sentence.tatoeba.TatoebaSentences._load_links`), which is exactly
what a CLI-level test must not depend on. `build_partial_export` itself is
covered directly, with fakes standing in for Kaikki/Tatoeba, in
`tests/test_lexicon_curation.py`.
"""

import pytest

from emmio import postgres
from tests.test_command_line.test_core import check_main, initialize


def test_build_partial_unknown_list_prints_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No curated list with that id: a clear message, not a crash."""

    initialize()

    check_main(capsys, user_commands=["data build-partial 999999", "exit"])

    assert postgres.get_curated_list(999999) is None
