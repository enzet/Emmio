"""Tests for `CuratedSentences` and its data-layer wiring."""

import json
from pathlib import Path

from emmio.language import KnownLanguages
from emmio.sentence.config import SentencesUsageConfig
from emmio.sentence.core import CuratedSentences
from emmio.sentence.data import SentencesData


def test_curated_sentences_get(tmp_path: Path) -> None:
    """`get` returns sentences for a known word, none for an unknown one."""

    file_path: Path = tmp_path / "10.json"
    file_path.write_text(
        json.dumps({"аа": ["Це аа.", "Аа не є аб."]}), encoding="utf-8"
    )

    sentences = CuratedSentences.from_file(
        file_path, "curated_10", KnownLanguages.UKRAINIAN
    )

    found = sentences.get("аа")
    assert [result.sentence.text for result in found] == [
        "Це аа.",
        "Аа не є аб.",
    ]
    assert all(result.translations == {} for result in found)
    assert sentences.get("missing") == []


def test_sentences_data_partial_dictionary_missing_is_none(
    tmp_path: Path,
) -> None:
    """No `curated/<id>.json` file yet: `None`, not an error."""

    data = SentencesData.from_config(tmp_path)

    assert data.get_partial_sentences(1, KnownLanguages.UKRAINIAN) is None
    assert data.has_partial(1, KnownLanguages.UKRAINIAN) is False


def test_sentences_data_get_dispatches_to_partial(tmp_path: Path) -> None:
    """`get`'s `curated_<id>` dispatch loads and caches the export.

    Covers the path a curated-backed lexicon actually uses (see
    `_curated_translation_config` in `emmio.api.app`).
    """

    curated_directory: Path = tmp_path / "curated"
    curated_directory.mkdir()
    (curated_directory / "10.json").write_text(
        json.dumps({"аа": ["Це аа."]}), encoding="utf-8"
    )

    data = SentencesData.from_config(tmp_path)

    assert data.has_partial(10, KnownLanguages.UKRAINIAN) is True
    partial = data.get_partial_sentences(10, KnownLanguages.UKRAINIAN)
    assert isinstance(partial, CuratedSentences)
    # Cached: a second lookup returns the exact same instance.
    assert data.get_partial_sentences(10, KnownLanguages.UKRAINIAN) is partial

    results = data.get(
        "аа", [SentencesUsageConfig(id="curated_10", language="uk")]
    )
    assert [result.sentence.text for result in results] == ["Це аа."]


def test_sentences_data_get_missing_partial_returns_nothing(
    tmp_path: Path,
) -> None:
    """A curated id with no export yet: no sentences, no crash."""

    data = SentencesData.from_config(tmp_path)

    results = data.get(
        "аа", [SentencesUsageConfig(id="curated_999", language="uk")]
    )
    assert results == []
