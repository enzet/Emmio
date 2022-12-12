from datetime import datetime
from pathlib import Path

from emmio.lexicon.config import LexiconConfig
from emmio.lexicon.core import (
    Lexicon,
    LexiconLog,
    LexiconResponse,
    WordSelection,
)


def test_lexicon() -> None:
    """Test lexicon checking process."""
    temp_directory: Path = Path("tests") / "temp"
    temp_directory.mkdir(exist_ok=True)
    lexicon: Lexicon = Lexicon(
        temp_directory,
        LexiconConfig(path="en.json", language="en", frequency_list="en"),
    )
    lexicon.add_log(LexiconLog("log", WordSelection.ARBITRARY))
    lexicon.register("apple", LexiconResponse.KNOW, False, datetime(2000, 1, 1))
    assert len(lexicon.responses) == 1
    assert lexicon.has("apple")
    assert lexicon.get("apple") == LexiconResponse.KNOW
