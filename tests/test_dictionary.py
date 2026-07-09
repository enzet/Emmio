"""Test for dictionary."""

import threading
from pathlib import Path
from typing import Any

import pytest

from emmio.dictionary import data as dictionary_data
from emmio.dictionary.config import DictionaryUsageConfig
from emmio.dictionary.core import SimpleDictionary
from emmio.dictionary.data import DictionaryData
from emmio.dictionary.en_wiktionary import (
    EnglishWiktionaryKaikki,
    kaikki_language_name,
)
from emmio.language import KnownLanguages


def test_dictionary() -> None:
    """Test simple dictionary creation."""

    SimpleDictionary(
        "test_dictionary",
        Path("test/dictionary/test_dictionary.txt"),
        "Test Dictionary",
        {"livre": "book", "chat": "cat"},
        KnownLanguages.FRENCH,
        KnownLanguages.ENGLISH,
    )


def test_can_download_kaikki() -> None:
    """Kaikki availability is decided by the catalog, not the download state."""

    assert DictionaryData.can_download_kaikki(KnownLanguages.TURKISH)
    # Greek's kaikki.org name differs from Emmio's, but the override finds it.
    assert DictionaryData.can_download_kaikki(KnownLanguages.MODERN_GREEK)
    # Serbian has no English-Wiktionary extraction under that name.
    assert not DictionaryData.can_download_kaikki(KnownLanguages.SERBIAN)


def test_kaikki_language_name_overrides() -> None:
    """Languages whose kaikki.org name differs from `get_name()` are mapped."""

    assert kaikki_language_name(KnownLanguages.MODERN_GREEK) == "Greek"
    assert kaikki_language_name(KnownLanguages.SINHALA) == "Sinhalese"
    assert kaikki_language_name(KnownLanguages.SLOVENIAN) == "Slovene"
    # Languages that already match keep their `get_name()`.
    assert kaikki_language_name(KnownLanguages.TURKISH) == "Turkish"


def test_kaikki_downloads_in_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An undownloaded Kaikki is fetched in the background, not in the request.

    The first lookup returns nothing (the lexicon falls back to its other
    dictionaries) and schedules the download; once the cache is built a later
    lookup returns the dictionary.
    """
    built = threading.Event()

    class FakeKaikki(EnglishWiktionaryKaikki):
        # A Kaikki instance without the real (huge) download: just build the
        # cache directory `has_kaikki` looks for. Subclasses the real class so
        # it is a `Dictionary` instance.
        def __init__(
            self, _path: Path, cache: Path, _language: Any, name: str
        ) -> None:
            (cache / "kaikki" / name).mkdir(parents=True, exist_ok=True)
            built.set()

    monkeypatch.setattr(dictionary_data, "EnglishWiktionaryKaikki", FakeKaikki)

    data = DictionaryData.from_config(tmp_path)
    config = DictionaryUsageConfig(
        id="kaikki", from_language="tr", name=KnownLanguages.TURKISH.get_name()
    )

    # Not downloaded yet: no dictionary now, but a build is scheduled.
    assert data.get_dictionary(config) is None
    assert built.wait(timeout=5)

    # Cache is ready: the dictionary is now returned.
    assert data.has_kaikki(KnownLanguages.TURKISH)
    assert data.get_dictionary(config) is not None
