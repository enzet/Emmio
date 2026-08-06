"""Test for dictionary."""

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from emmio.dictionary import data as dictionary_data
from emmio.dictionary.config import DictionaryConfig, DictionaryUsageConfig
from emmio.dictionary.core import (
    Commonality,
    Definition,
    DefinitionValue,
    DictionaryItem,
    Form,
    Link,
    SimpleDictionary,
    StructuredDictionary,
)
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


def test_commonality_letter() -> None:
    """A `letter` part of speech is confirmed junk both ways."""

    form = Form("a", part_of_speech="letter")
    assert form.get_commonality(KnownLanguages.ENGLISH) == Commonality.LETTER
    assert form.get_commonality(KnownLanguages.ENGLISH).is_confirmed_junk()
    assert form.is_not_common(KnownLanguages.ENGLISH) is True


def test_commonality_common_definition() -> None:
    """A common definition confirms the word both ways."""

    form = Form(
        "book",
        definitions={
            KnownLanguages.ENGLISH: [Definition([DefinitionValue("a book")])]
        },
    )
    commonality = form.get_commonality(KnownLanguages.ENGLISH)
    assert commonality == Commonality.COMMON
    assert not commonality.is_confirmed_junk()
    assert form.is_not_common(KnownLanguages.ENGLISH) is False


def test_commonality_uncommon_definition() -> None:
    """Definitions exist but none are common: confirmed junk both ways."""

    form = Form(
        "foo",
        definitions={
            KnownLanguages.ENGLISH: [
                Definition([DefinitionValue("foo")], descriptors=["obsolete"])
            ]
        },
    )
    commonality = form.get_commonality(KnownLanguages.ENGLISH)
    assert commonality == Commonality.UNCOMMON_DEFINITION
    assert commonality.is_confirmed_junk()
    assert form.is_not_common(KnownLanguages.ENGLISH) is True


def test_commonality_form_of_another_word_is_real() -> None:
    """A linked form is real for curation, "not common" for teaching."""

    form = Form("books", links=[Link("plural form of", "book")])
    commonality = form.get_commonality(KnownLanguages.ENGLISH)
    assert commonality == Commonality.FORM_OF_ANOTHER_WORD
    assert not commonality.is_confirmed_junk()  # Real word for curation.
    assert form.is_not_common(KnownLanguages.ENGLISH) is True  # Unchanged.


def test_commonality_unknown_is_not_evidence() -> None:
    """No definitions and no links: unresolved, not evidence either way."""

    form = Form("xyzzy")
    commonality = form.get_commonality(KnownLanguages.ENGLISH)
    assert commonality == Commonality.UNKNOWN
    assert not commonality.is_confirmed_junk()
    assert form.is_not_common(KnownLanguages.ENGLISH) is False


def test_dictionary_item_commonality_prefers_confirming_form() -> None:
    """One confirming form is enough to confirm the whole item."""

    item = DictionaryItem(
        "bank",
        [
            Form("bank", part_of_speech="letter"),  # Junk on its own.
            Form(
                "bank",
                definitions={
                    KnownLanguages.ENGLISH: [
                        Definition([DefinitionValue("a financial institution")])
                    ]
                },
            ),
        ],
    )
    assert item.get_commonality(KnownLanguages.ENGLISH) == Commonality.COMMON
    # Legacy `all()` view: one common form still makes the item common.
    assert item.is_not_common(KnownLanguages.ENGLISH) is False


def test_dictionary_item_commonality_all_junk() -> None:
    """Only when every form is confirmed junk is the item confirmed junk."""

    item = DictionaryItem("xyz", [Form("xyz", part_of_speech="letter")])
    assert item.get_commonality(KnownLanguages.ENGLISH) == Commonality.LETTER
    assert item.is_not_common(KnownLanguages.ENGLISH) is True


def test_dictionary_item_commonality_empty_forms_is_unknown() -> None:
    """An item with no forms is unresolved, not confirmed junk."""

    item = DictionaryItem("xyz", [])
    assert item.get_commonality(KnownLanguages.ENGLISH) == Commonality.UNKNOWN


_ARMENIAN_ALPHABET_ENTRY: dict[str, Any] = {
    "part_of_speech": "letter",
    "transcriptions": ["ɑ"],
    "definitions": {"hy": ["այբ"], "en": ["ayb"], "ru": ["айб"]},
    "links": [{"type": "lowercase form", "value": "ա"}],
}


def test_structured_dictionary_get_item() -> None:
    """`StructuredDictionary.get_item` looks up its pre-built items by word."""

    item = DictionaryItem(
        "Ա",
        [
            Form(
                "Ա",
                part_of_speech="letter",
                transcriptions={"ɑ"},
                definitions={
                    KnownLanguages.ARMENIAN: [
                        Definition([DefinitionValue("այբ")])
                    ],
                    KnownLanguages.ENGLISH: [
                        Definition([DefinitionValue("ayb")])
                    ],
                },
                links=[Link("lowercase form", "ա")],
            )
        ],
    )
    dictionary = StructuredDictionary(
        "hy_alphabet",
        Path("unused"),
        "Armenian alphabet",
        {"Ա": item},
        KnownLanguages.ARMENIAN,
    )

    found = asyncio.run(dictionary.get_item("Ա"))
    assert found is item
    assert asyncio.run(dictionary.get_item("missing")) is None
    assert dictionary.check_from_language(KnownLanguages.ARMENIAN)
    assert not dictionary.check_from_language(KnownLanguages.ENGLISH)
    assert dictionary.check_to_language(KnownLanguages.ENGLISH)
    assert not dictionary.check_to_language(KnownLanguages.RUSSIAN)


def test_dictionary_data_loads_structured_type(tmp_path: Path) -> None:
    """`type: "structured"` in `config.json` dispatches to it.

    The parsed item should carry definitions, transcriptions, and links from
    plain JSON.
    """

    (tmp_path / "hy_alphabet.json").write_text(
        json.dumps({"Ա": _ARMENIAN_ALPHABET_ENTRY}), encoding="utf-8"
    )
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "hy_alphabet": {
                    "type": "structured",
                    "file_name": "hy_alphabet.json",
                    "name": "Armenian alphabet",
                    "from_language": "hy",
                }
            }
        ),
        encoding="utf-8",
    )

    data = DictionaryData.from_config(tmp_path)

    dictionary = data.get_dictionary(
        DictionaryUsageConfig(id="hy_alphabet", from_language="hy")
    )
    assert isinstance(dictionary, StructuredDictionary)
    item = asyncio.run(dictionary.get_item("Ա"))
    assert item is not None
    form = item.get_forms()[0]
    assert form.part_of_speech == "letter"
    assert form.transcriptions == {"ɑ"}
    assert form.definitions[KnownLanguages.ARMENIAN][0].values[0].value == (
        "այբ"
    )
    assert form.definitions[KnownLanguages.ENGLISH][0].values[0].value == (
        "ayb"
    )
    assert [link.link_value for link in form.get_links()] == ["ա"]


def test_dictionary_config_defaults_to_file_type() -> None:
    """Omitting `type` keeps the long-standing flat-file behavior."""

    config = DictionaryConfig(
        file_name="nb_en.json",
        name="Norwegian Bokmål-English Dictionary",
        from_language="nb",
        to_language="en",
    )
    assert config.type == "file"


def test_simple_dictionary_requires_to_language(tmp_path: Path) -> None:
    """A `file`-type dictionary without `to_language` is a clear error."""

    (tmp_path / "d.json").write_text("{}", encoding="utf-8")
    config = DictionaryConfig(
        file_name="d.json", name="Test", from_language="nb"
    )

    with pytest.raises(ValueError, match="to_language"):
        SimpleDictionary.from_config(tmp_path, "d", config)


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


def test_kaikki_ignores_a_stale_or_wrong_config_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`get_dictionary` always derives kaikki.org's name itself.

    Regression test: every call site used to build `DictionaryUsageConfig`
    with `name=language.get_name()`, bypassing `kaikki_language_name`
    entirely — for Greek that means `name="Modern Greek"`, which 404s on
    kaikki.org (whose actual name is "Greek"), so the download failed for
    this language (and Sinhala, Slovenian) no matter which code path called
    it. Passing that same wrong name here must still resolve to "Greek",
    proving `get_dictionary` no longer trusts it.
    """
    built = threading.Event()
    built_name: list[str] = []

    class FakeKaikki(EnglishWiktionaryKaikki):
        def __init__(
            self, _path: Path, cache: Path, _language: Any, name: str
        ) -> None:
            built_name.append(name)
            (cache / "kaikki" / name).mkdir(parents=True, exist_ok=True)
            built.set()

    monkeypatch.setattr(dictionary_data, "EnglishWiktionaryKaikki", FakeKaikki)

    data = DictionaryData.from_config(tmp_path)
    config = DictionaryUsageConfig(
        id="kaikki", from_language="el", name="Modern Greek"
    )

    assert data.get_dictionary(config) is None  # Download scheduled first.
    assert built.wait(timeout=5)

    assert built_name == ["Greek"]
    assert data.has_kaikki(KnownLanguages.MODERN_GREEK)


def test_dictionary_data_partial_dictionary_missing_is_none(
    tmp_path: Path,
) -> None:
    """No `curated/<id>.json` file yet: `None`, not an error."""

    data = DictionaryData.from_config(tmp_path)

    assert data.get_partial_dictionary(1) is None
    assert data.has_partial(1) is False


def test_dictionary_data_partial_dictionary_loads_and_caches(
    tmp_path: Path,
) -> None:
    """A curated list's export loads as a `StructuredDictionary` and caches.

    Also covers `get_dictionary`'s `curated_<id>` dispatch, the path a
    curated-backed lexicon actually uses (see `_curated_translation_config`
    in `emmio.api.app`).
    """

    curated_directory: Path = tmp_path / "curated"
    curated_directory.mkdir()
    (curated_directory / "10.json").write_text(
        json.dumps({"аа": _ARMENIAN_ALPHABET_ENTRY}), encoding="utf-8"
    )

    data = DictionaryData.from_config(tmp_path)

    assert data.has_partial(10) is True
    dictionary = data.get_partial_dictionary(10)
    assert isinstance(dictionary, StructuredDictionary)
    item = asyncio.run(dictionary.get_item("аа"))
    assert item is not None
    assert item.get_forms()[0].part_of_speech == "letter"

    # Cached: a second lookup returns the exact same instance.
    assert data.get_partial_dictionary(10) is dictionary

    via_usage_config = data.get_dictionary(
        DictionaryUsageConfig(id="curated_10", from_language="uk")
    )
    assert via_usage_config is dictionary
