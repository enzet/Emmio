from datetime import datetime
from pathlib import Path

from emmio.language import ENGLISH
from emmio.lexicon import Lexicon, LexiconResponse, LexiconLog, WordSelection


def test_lexicon() -> None:
    lexicon: Lexicon = Lexicon(ENGLISH, Path("temp/en.json"))
    lexicon.add_log(LexiconLog("log", WordSelection.ARBITRARY))
    lexicon.register("apple", LexiconResponse.KNOW, False, datetime(2000, 1, 1))
    assert len(lexicon.responses) == 1
    assert lexicon.has("apple")
    assert lexicon.get("apple") == LexiconResponse.KNOW
