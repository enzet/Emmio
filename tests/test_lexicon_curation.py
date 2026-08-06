"""Tests for `emmio.lexicon.curation.build_partial_export`."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from emmio import postgres
from emmio.dictionary.core import (
    Definition,
    DefinitionValue,
    DictionaryCollection,
    DictionaryItem,
    Form,
    StructuredDictionary,
)
from emmio.language import KnownLanguages
from emmio.lexicon.curation import PartialExportError, build_partial_export
from emmio.sentence.core import Sentence, SentenceAndTranslations


class _FakeSentencesData:
    """Stand-in for `SentencesData`: a fixed word-to-sentence-texts map."""

    def __init__(self, path: Path, examples: dict[str, list[str]]) -> None:
        self.path = path
        self._examples = examples

    def get(
        self,
        word: str,
        usage_configs: object,  # noqa: ARG002
        max_number: int = 1000,
    ) -> list[SentenceAndTranslations]:
        texts = self._examples.get(word, [])
        return [
            SentenceAndTranslations(
                Sentence(index, text), KnownLanguages.UKRAINIAN, {}
            )
            for index, text in enumerate(texts)
        ][:max_number]


class _FakeData:
    """Stand-in for `Data`: a fixed Kaikki-like dictionary and sentences."""

    def __init__(
        self,
        dictionaries_path: Path,
        dictionary_collection: DictionaryCollection,
        sentences_data: _FakeSentencesData,
    ) -> None:
        self.dictionaries: Any = type(
            "_Dictionaries", (), {"path": dictionaries_path}
        )()
        self._dictionary_collection = dictionary_collection
        self._sentences_data = sentences_data

    def get_dictionaries(self, usage_configs: object) -> DictionaryCollection:  # noqa: ARG002
        return self._dictionary_collection

    def get_sentences_data(self) -> _FakeSentencesData:
        return self._sentences_data


def _make_item(word: str, gloss: str) -> DictionaryItem:
    """Build a one-form, one-gloss `DictionaryItem`, like Kaikki's own."""
    form = Form(
        word,
        part_of_speech="noun",
        transcriptions={f"/{word}/"},
        definitions={
            KnownLanguages.ENGLISH: [Definition([DefinitionValue(gloss)])]
        },
    )
    return DictionaryItem(word, [form])


def test_build_partial_export_covers_only_confirmed_real_words(
    tmp_path: Path,
) -> None:
    """Only `category = 'W'` words are exported.

    Each exported word carries its Kaikki gloss and example sentences.
    """

    list_id: int = postgres.create_curated_list(
        "uk", "uk_list", "UK Curated", n_strata=1
    )
    postgres.add_curated_words(
        list_id, [("аа", 0, 0, "bootstrap"), ("аб", 0, 1, "bootstrap")]
    )
    postgres.ensure_user("curator", "Curator")
    postgres.record_curation_vote(list_id, "аа", "W", "curator")
    postgres.record_curation_vote(list_id, "аб", "P", "curator")

    dictionary = StructuredDictionary(
        "kaikki",
        Path("unused"),
        "Fake Kaikki",
        {"аа": _make_item("аа", "a word")},
        KnownLanguages.UKRAINIAN,
    )
    dictionaries_path: Path = tmp_path / "dictionaries"
    sentences_path: Path = tmp_path / "sentences"
    data = _FakeData(
        dictionaries_path,
        DictionaryCollection([dictionary]),
        _FakeSentencesData(sentences_path, {"аа": ["Це аа."]}),
    )

    result = asyncio.run(build_partial_export(data, list_id))

    assert result.list_id == list_id
    assert result.words == 1
    assert result.dictionary_entries == 1
    assert result.sentence_entries == 1

    with (dictionaries_path / "curated" / f"{list_id}.json").open(
        encoding="utf-8"
    ) as input_file:
        dictionary_export: dict = json.load(input_file)
    assert set(dictionary_export) == {"аа"}
    assert dictionary_export["аа"]["definitions"] == {"en": ["a word"]}

    with (sentences_path / "curated" / f"{list_id}.json").open(
        encoding="utf-8"
    ) as input_file:
        sentences_export: dict = json.load(input_file)
    assert sentences_export == {"аа": ["Це аа."]}


def test_build_partial_export_is_rerunnable(tmp_path: Path) -> None:
    """Running it again overwrites the export rather than erroring."""

    list_id: int = postgres.create_curated_list(
        "uk", "uk_list", "UK Curated", n_strata=1
    )
    postgres.add_curated_words(list_id, [("аа", 0, 0, "bootstrap")])
    postgres.ensure_user("curator", "Curator")
    postgres.record_curation_vote(list_id, "аа", "W", "curator")

    dictionaries_path: Path = tmp_path / "dictionaries"
    sentences_path: Path = tmp_path / "sentences"
    data = _FakeData(
        dictionaries_path,
        DictionaryCollection([]),
        _FakeSentencesData(sentences_path, {}),
    )

    asyncio.run(build_partial_export(data, list_id))
    result = asyncio.run(build_partial_export(data, list_id))

    assert result.words == 1
    assert result.dictionary_entries == 0
    assert result.sentence_entries == 0


def test_build_partial_export_unknown_list_raises(tmp_path: Path) -> None:
    """A bad list id is a clear error, not a crash."""

    data = _FakeData(
        tmp_path / "dictionaries",
        DictionaryCollection([]),
        _FakeSentencesData(tmp_path / "sentences", {}),
    )

    with pytest.raises(PartialExportError):
        asyncio.run(build_partial_export(data, 999_999))
