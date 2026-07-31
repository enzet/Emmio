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
