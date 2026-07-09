"""Tests for the static downloadable-language catalogs."""

from pathlib import Path

from emmio.catalog import (
    FREQUENCY_WORDS_YEARS,
    KAIKKI_LANGUAGES,
    TATOEBA_LANGUAGES,
)
from emmio.language import KnownLanguages
from emmio.lists.data import ListsData
from emmio.sentence.data import SentencesData

_KNOWN: set[str] = {
    language.get_code() for language in KnownLanguages.get_languages()
}


def test_frequency_words_catalog_is_well_formed() -> None:
    """Every FrequencyWords entry is a known code with a real release year."""

    assert FREQUENCY_WORDS_YEARS
    for code, year in FREQUENCY_WORDS_YEARS.items():
        assert code in _KNOWN, code
        assert year in {2016, 2018}, (code, year)
    # Thai and Chinese only exist in the 2016 release.
    assert FREQUENCY_WORDS_YEARS["th"] == 2016
    assert FREQUENCY_WORDS_YEARS["zh"] == 2016


def test_kaikki_catalog_is_well_formed() -> None:
    """Every Kaikki entry is a known code; Turkish and English are present."""

    assert KAIKKI_LANGUAGES
    assert KAIKKI_LANGUAGES <= _KNOWN
    assert {"tr", "en"} <= KAIKKI_LANGUAGES


def test_tatoeba_catalog_is_well_formed() -> None:
    """Every Tatoeba entry is a language Emmio knows a two-letter code for."""

    assert TATOEBA_LANGUAGES
    assert TATOEBA_LANGUAGES <= _KNOWN
    # Emmio downloads Tatoeba by ISO 639-3 code, which has no `zho`/`nor`
    # export, so these macrolanguages are not offered.
    assert "zh" not in TATOEBA_LANGUAGES
    assert "no" not in TATOEBA_LANGUAGES


def test_new_languages_are_offerable(tmp_path: Path) -> None:
    """With nothing downloaded, catalog languages are still offered.

    The lexicon picker intersects frequency-list and sentence languages; a
    representative sample of the newly added languages must appear from the
    catalogs alone (no files on disk).
    """
    (tmp_path / "lists").mkdir()
    (tmp_path / "sentences" / "cache").mkdir(parents=True)

    lists = ListsData.from_config(tmp_path / "lists")
    sentences = SentencesData.from_config(tmp_path / "sentences")
    offerable: set[str] = (
        set(lists.get_frequency_list_languages())
        & sentences.get_supported_languages()
    )
    assert {"cs", "nl", "tr", "vi", "th"} <= offerable


def test_frequency_words_config_uses_catalog_year(tmp_path: Path) -> None:
    """A catalog language yields a `frequency_words` config with a best year."""

    (tmp_path / "lists").mkdir()
    languages = ListsData.from_config(
        tmp_path / "lists"
    ).get_frequency_list_languages()

    assert languages["cs"] == {
        "id": "frequency_words",
        "language": "cs",
        "year": 2018,
    }
    assert languages["th"] == {
        "id": "frequency_words",
        "language": "th",
        "year": 2016,
    }


def test_supported_languages_includes_downloadable(tmp_path: Path) -> None:
    """`get_supported_languages` reports catalog languages without downloads."""

    (tmp_path / "cache").mkdir()
    supported = SentencesData.from_config(tmp_path).get_supported_languages()
    assert supported >= TATOEBA_LANGUAGES
