"""Tests for the static downloadable-language catalogs."""

from pathlib import Path

from emmio.catalog import (
    FREQUENCY_WORDS_YEARS,
    KAIKKI_LANGUAGES,
    NON_PROPER_NOUNS,
    TATOEBA_LANGUAGES,
)
from emmio.language import KnownLanguages
from emmio.lists.config import ListUsageConfig
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


def test_non_proper_nouns_catalog_is_well_formed() -> None:
    """Every entry maps a `freqlist`-style code to lowercase words.

    Scoped to `freqlist`'s own language coverage (Tier 1/2.5 of its README),
    not to Emmio's `KnownLanguages` registry, so codes such as `lv` and `ms`
    are expected even though Emmio does not yet register those languages.
    `unis` (a fragment of French `les États-Unis`) is present as a
    documented example of the category.
    """

    assert NON_PROPER_NOUNS
    for code, words in NON_PROPER_NOUNS.items():
        assert code, code
        assert isinstance(words, frozenset)
        for word in words:
            assert word == word.lower(), word
    assert "unis" in NON_PROPER_NOUNS["fr"]


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


def test_frequency_list_options_offer_every_cached_year(tmp_path: Path) -> None:
    """Two cached FrequencyWords years for a language offer both, newest first.

    The default `get_frequency_list_languages` picks (the newest cached year)
    must be the first option returned for that language.
    """
    lists_path = tmp_path / "lists"
    lists_path.mkdir()
    (lists_path / "fr_frequency_words_2016.txt").touch()
    (lists_path / "fr_frequency_words_2018.txt").touch()

    lists = ListsData.from_config(lists_path)
    options = [
        option
        for option in lists.get_frequency_list_options()
        if option["language"] == "fr"
    ]

    assert [option["config"]["year"] for option in options] == [2018, 2016]
    assert options[0]["config"] == lists.get_frequency_list_languages()["fr"]


def test_opensubtitles_files_are_recognized_alongside_frequency_words(
    tmp_path: Path,
) -> None:
    """`_opensubtitles_` files get their own `id`, no collision with FW."""

    lists_path = tmp_path / "lists"
    lists_path.mkdir()
    (lists_path / "de_opensubtitles_2024.txt").touch()
    (lists_path / "de_frequency_words_2016.txt").touch()

    lists = ListsData.from_config(lists_path)
    options = {
        option["config"]["id"]: option
        for option in lists.get_frequency_list_options()
        if option["language"] == "de"
    }

    assert options.keys() == {"opensubtitles", "frequency_words"}
    assert options["opensubtitles"]["config"] == {
        "id": "opensubtitles",
        "language": "de",
        "year": 2024,
    }
    assert options["opensubtitles"]["name"] == "OpenSubtitles (2024)"


def test_get_frequency_list_loads_opensubtitles_file(tmp_path: Path) -> None:
    """`get_frequency_list` loads an `_opensubtitles_` file with `cap_ratio`."""

    lists_path = tmp_path / "lists"
    lists_path.mkdir()
    (lists_path / "de_opensubtitles_2024.txt").write_text(
        "ich 100 0.01\nkatze 3 1.00\n"
    )

    lists = ListsData.from_config(lists_path)
    frequency_list = lists.get_frequency_list(
        ListUsageConfig(id="opensubtitles", language="de", year=2024)
    )

    assert frequency_list is not None
    assert frequency_list.get_occurrences("ich") == 100
    assert frequency_list.get_cap_ratio("katze") == 1.0


def test_get_frequency_list_missing_opensubtitles_file_is_none(
    tmp_path: Path,
) -> None:
    """A missing `_opensubtitles_` file is reported as absent, not a crash.

    Unlike `frequency_words`, there is no download fallback here — the file
    either already exists or it doesn't.
    """
    lists_path = tmp_path / "lists"
    lists_path.mkdir()

    lists = ListsData.from_config(lists_path)
    frequency_list = lists.get_frequency_list(
        ListUsageConfig(id="opensubtitles", language="de", year=2024)
    )

    assert frequency_list is None


def test_supported_languages_includes_downloadable(tmp_path: Path) -> None:
    """`get_supported_languages` reports catalog languages without downloads."""

    (tmp_path / "cache").mkdir()
    supported = SentencesData.from_config(tmp_path).get_supported_languages()
    assert supported >= TATOEBA_LANGUAGES
