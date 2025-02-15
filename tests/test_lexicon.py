from datetime import datetime
from pathlib import Path

import pytest

from emmio.lexicon.config import LexiconConfig
from emmio.lexicon.core import (
    Lexicon,
    LexiconLog,
    LexiconResponse,
    WordSelection,
)


@pytest.mark.skip(reason="Fix lexicon creation.")
def test_lexicon() -> None:
    """Test lexicon checking process."""
    temp_directory: Path = Path("/tmp") / "emmio_test_temp_directory"
    temp_directory.mkdir(exist_ok=True)
    lexicon: Lexicon = Lexicon(
        temp_directory,
        LexiconConfig(
            file_name="en.json",
            language="en",
            frequency_list="en",
            selection="arbitrary",
        ),
    )
    lexicon.add_log(LexiconLog("log", WordSelection.ARBITRARY))
    lexicon.register("apple", LexiconResponse.KNOW, False, datetime(2000, 1, 1))
    assert len(lexicon.responses) == 1
    assert lexicon.has("apple")
    assert lexicon.get("apple") == LexiconResponse.KNOW
