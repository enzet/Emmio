"""Tests for the shared data artifact inventory."""

import json
from pathlib import Path

import pytest

from emmio import inventory
from emmio.language import KnownLanguages

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


def test_format_size() -> None:
    """Sizes are shortened to a human-readable unit."""

    assert inventory.format_size(None) == "—"
    assert inventory.format_size(0) == "0 B"
    assert inventory.format_size(999) == "999 B"
    assert inventory.format_size(1_200) == "1.2 kB"
    assert inventory.format_size(990_394_100) == "990.4 MB"
    assert inventory.format_size(3_431_378_944) == "3.4 GB"


def test_empty_directory_offers_available_artifacts(tmp_path: Path) -> None:
    """With nothing on disk, everything known is offered as available."""

    dictionaries = inventory.dictionary_artifacts(tmp_path)
    assert dictionaries
    assert not any(artifact.downloaded for artifact in dictionaries)

    lists = inventory.list_artifacts(tmp_path)
    assert {artifact.name for artifact in lists} == {"FrequencyWords"}
    assert not any(artifact.downloaded for artifact in lists)


def test_downloaded_artifacts_are_reported(tmp_path: Path) -> None:
    """Downloaded artifacts carry their size and location on disk."""

    # A downloaded Kaikki dictionary is a per-prefix cache directory.
    kaikki = tmp_path / "dictionaries" / "cache" / "kaikki" / "French"
    kaikki.mkdir(parents=True)
    (kaikki / "a.json").write_text('{"a": 1}')
    # A downloaded Tatoeba export is a per-language cache file.
    sentences_cache = tmp_path / "sentences" / "cache"
    sentences_cache.mkdir(parents=True)
    (sentences_cache / "fra_sentences.tsv.bz2").write_bytes(b"data")
    # A downloaded FrequencyWords list is a plain file in `lists`.
    lists_path = tmp_path / "lists"
    lists_path.mkdir()
    (lists_path / "uk_frequency_words_2018.txt").write_text("slovo 5\n")

    def by_language(
        artifacts: list[inventory.Artifact], language: str
    ) -> inventory.Artifact:
        return next(x for x in artifacts if x.language == language)

    dictionaries = inventory.dictionary_artifacts(tmp_path)
    french_kaikki = by_language(dictionaries, "fr")
    assert french_kaikki.downloaded is True
    assert french_kaikki.size == len('{"a": 1}')
    assert french_kaikki.path == "dictionaries/cache/kaikki/French"
    # Ukrainian Kaikki is not downloaded, but it is available.
    assert by_language(dictionaries, "uk").downloaded is False

    sentences = inventory.sentence_artifacts(tmp_path)
    french_sentences = by_language(sentences, "fr")
    assert french_sentences.downloaded is True
    assert french_sentences.path == "sentences/cache/fra_sentences.tsv.bz2"
    assert by_language(sentences, "uk").downloaded is False

    lists = inventory.list_artifacts(tmp_path)
    ukrainian_list = by_language(lists, "uk")
    assert ukrainian_list.downloaded is True
    assert ukrainian_list.name == "FrequencyWords 2018"
    assert by_language(lists, "fr").downloaded is False


def test_configured_artifacts_are_reported(tmp_path: Path) -> None:
    """Artifacts configured in `config.json` files are inventoried."""

    lists_path = tmp_path / "lists"
    lists_path.mkdir()
    (lists_path / "config.json").write_text(
        '{"eo_2011": {"type": "frequency_list", "name": "Esperanto 2011", '
        '"language": "eo", "path": "eo_2011.txt", "file_format": "list", '
        '"is_stripped": false}}'
    )
    (lists_path / "eo_2011.txt").write_text("vorto 5\n")

    lists = inventory.list_artifacts(tmp_path)
    esperanto = next(x for x in lists if x.language == "eo")
    assert esperanto.name == "Esperanto 2011"
    assert esperanto.kind == "file"
    assert esperanto.downloaded is True
    # A configured language is not offered a FrequencyWords list again.
    assert [x for x in lists if x.language == "eo"] == [esperanto]


def test_artifacts_are_sorted(tmp_path: Path) -> None:
    """Downloaded artifacts come first, largest first."""

    lists_path = tmp_path / "lists"
    lists_path.mkdir()
    (lists_path / "uk_frequency_words_2018.txt").write_text("slovo 5\n")
    (lists_path / "fr_frequency_words_2018.txt").write_text(
        "mot 7\nchat 5\nchien 3\n"
    )

    lists = inventory.list_artifacts(tmp_path)

    downloaded_flags = [x.downloaded for x in lists]
    assert downloaded_flags == sorted(downloaded_flags, reverse=True)
    sizes = [x.size for x in lists if x.downloaded]
    assert sizes == sorted(sizes, reverse=True)
    assert [x.language for x in lists if x.downloaded] == ["fr", "uk"]


def test_add_and_delete_configured(tmp_path: Path) -> None:
    """`add_configured` registers an artifact; `delete_configured` undoes it.

    Deletion removes both the configuration entry and the artifact's file.
    """

    entry = {
        "type": "frequency_list",
        "language": "eo",
        "path": "eo_2011.txt",
        "file_format": "list",
        "is_stripped": False,
    }
    file_path, exists = inventory.add_configured(
        tmp_path, "lists", "eo_2011", entry
    )
    assert file_path == tmp_path / "lists" / "eo_2011.txt"
    assert exists is False

    file_path.write_text("vorto 5\n")
    assert [
        x.language for x in inventory.list_artifacts(tmp_path) if x.downloaded
    ] == ["eo"]

    removed, size = inventory.delete_configured(tmp_path, "eo_2011", None)
    assert removed == [file_path]
    assert size == len("vorto 5\n")
    assert not file_path.exists()
    assert json.loads((tmp_path / "lists" / "config.json").read_text()) == {}


def test_add_configured_rejects_duplicate_and_invalid(tmp_path: Path) -> None:
    """A duplicate identifier or an invalid entry is rejected."""

    entry = {
        "type": "frequency_list",
        "language": "eo",
        "path": "eo.txt",
        "file_format": "list",
        "is_stripped": False,
    }
    inventory.add_configured(tmp_path, "lists", "eo", entry)
    with pytest.raises(inventory.InventoryError):
        inventory.add_configured(tmp_path, "lists", "eo", entry)
    with pytest.raises(inventory.InventoryError):
        inventory.add_configured(
            tmp_path, "lists", "bad", {"language": "eo", "path": "x.txt"}
        )


def test_delete_configured_ambiguity(tmp_path: Path) -> None:
    """The same identifier in two types needs an explicit type."""

    inventory.add_configured(
        tmp_path,
        "dictionaries",
        "shared",
        {
            "file_name": "shared.json",
            "name": "Shared",
            "from_language": "de",
            "to_language": "ru",
        },
    )
    inventory.add_configured(
        tmp_path,
        "lists",
        "shared",
        {
            "type": "frequency_list",
            "language": "de",
            "path": "shared.txt",
            "file_format": "list",
            "is_stripped": False,
        },
    )

    with pytest.raises(inventory.InventoryError, match="--type"):
        inventory.delete_configured(tmp_path, "shared", None)
    inventory.delete_configured(tmp_path, "shared", "lists")
    assert "shared" in json.loads(
        (tmp_path / "dictionaries" / "config.json").read_text()
    )

    with pytest.raises(inventory.InventoryError, match="No configured"):
        inventory.delete_configured(tmp_path, "unknown", None)


def test_delete_on_demand_artifacts(tmp_path: Path) -> None:
    """Downloaded Kaikki, Tatoeba, and FrequencyWords files are removable."""

    french = KnownLanguages.FRENCH

    kaikki = tmp_path / "dictionaries" / "cache" / "kaikki" / "French"
    kaikki.mkdir(parents=True)
    (kaikki / "a.json").write_text('{"a": 1}')
    removed, size = inventory.delete_kaikki(tmp_path, french)
    assert removed == [kaikki]
    assert size == len('{"a": 1}')
    assert not kaikki.exists()
    with pytest.raises(inventory.InventoryError):
        inventory.delete_kaikki(tmp_path, french)

    sentences = tmp_path / "sentences" / "cache" / "fra_sentences.tsv"
    sentences.parent.mkdir(parents=True)
    sentences.write_text("1\tfra\tBonjour.\n")
    removed, _ = inventory.delete_tatoeba(tmp_path, french)
    assert removed == [sentences]
    with pytest.raises(inventory.InventoryError):
        inventory.delete_tatoeba(tmp_path, french)


def test_delete_frequency_words_needs_year_when_several(tmp_path: Path) -> None:
    """With several downloaded years, deletion needs an explicit year."""

    french = KnownLanguages.FRENCH
    lists_path = tmp_path / "lists"
    lists_path.mkdir()
    (lists_path / "fr_frequency_words_2016.txt").write_text("mot 7\n")
    (lists_path / "fr_frequency_words_2018.txt").write_text("mot 9\n")

    with pytest.raises(inventory.InventoryError, match="2016, 2018"):
        inventory.delete_frequency_words(tmp_path, french, None)

    removed, _ = inventory.delete_frequency_words(tmp_path, french, 2016)
    assert removed == [lists_path / "fr_frequency_words_2016.txt"]
    # Only one year remains, so it no longer needs to be spelled out.
    removed, _ = inventory.delete_frequency_words(tmp_path, french, None)
    assert removed == [lists_path / "fr_frequency_words_2018.txt"]
    with pytest.raises(inventory.InventoryError):
        inventory.delete_frequency_words(tmp_path, french, None)


def test_download_frequency_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fetched list is stored; GitHub's 404 body is not mistaken for one."""

    def fake_download(address: str, cache_path: Path) -> bytearray:
        # GitHub answers a "404: Not Found" body for the Esperanto list.
        body = (
            bytearray(b"404: Not Found")
            if "/eo/" in address
            else bytearray(b"mot 7\n" * 200)
        )
        cache_path.write_bytes(body)
        return body

    monkeypatch.setattr(inventory, "download", fake_download)

    path, fetched = inventory.download_frequency_words(
        tmp_path, KnownLanguages.FRENCH, 2018
    )
    assert fetched is True
    assert path == tmp_path / "lists" / "fr_frequency_words_2018.txt"
    # A second call finds the file and does not fetch again.
    assert inventory.download_frequency_words(
        tmp_path, KnownLanguages.FRENCH, 2018
    ) == (path, False)

    with pytest.raises(inventory.InventoryError, match="has no"):
        inventory.download_frequency_words(
            tmp_path, KnownLanguages.ESPERANTO, 2018
        )
    assert not (tmp_path / "lists" / "eo_frequency_words_2018.txt").exists()


def test_download_tatoeba(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fetched export is unpacked; a placeholder response is rejected."""

    import bz2  # noqa: PLC0415

    # Varied lines, so the compressed archive stays above the size guard.
    lines = b"".join(
        f"{index}\tfra\tBonjour tout le monde numéro {index}.\n".encode()
        for index in range(2000)
    )

    def fake_download(_address: str, cache_path: Path) -> bytearray:
        body = bytearray(bz2.compress(lines))
        cache_path.write_bytes(body)
        return body

    monkeypatch.setattr(inventory, "download", fake_download)

    path, fetched = inventory.download_tatoeba(tmp_path, KnownLanguages.FRENCH)
    assert fetched is True
    assert path == tmp_path / "sentences" / "cache" / "fra_sentences.tsv"
    assert path.read_bytes() == lines
    assert not path.with_name(path.name + ".bz2").exists()
    assert inventory.download_tatoeba(tmp_path, KnownLanguages.FRENCH) == (
        path,
        False,
    )

    def placeholder_download(_address: str, cache_path: Path) -> bytearray:
        cache_path.write_bytes(b"tiny")
        return bytearray(b"tiny")

    monkeypatch.setattr(inventory, "download", placeholder_download)
    with pytest.raises(inventory.InventoryError, match="no sentences"):
        inventory.download_tatoeba(tmp_path, KnownLanguages.ESPERANTO)
    assert not (
        tmp_path / "sentences" / "cache" / "epo_sentences.tsv.bz2"
    ).exists()


def test_word_lists_are_inventoried(tmp_path: Path) -> None:
    """Word lists are listed with their type, next to frequency lists.

    A word list does not stand in for a frequency list, so its language is
    still offered a FrequencyWords download.
    """

    inventory.add_configured(
        tmp_path,
        "lists",
        "ja_kanji",
        {
            "type": "word_list",
            "language": "ja",
            "path": "ja_kanji.txt",
            "name": "Kanji list",
            "source": "personal knowledge",
        },
    )
    inventory.add_configured(
        tmp_path,
        "lists",
        "eo_cropped",
        {
            "type": "frequency_list",
            "language": "eo",
            "path": "eo_cropped.txt",
            "file_format": "list",
            "is_stripped": True,
        },
    )
    (tmp_path / "lists" / "ja_kanji.txt").write_text("空\n")

    lists = inventory.list_artifacts(tmp_path)

    kanji = next(x for x in lists if x.name == "Kanji list")
    assert kanji.list_type == "word list"
    assert kanji.downloaded is True

    cropped = next(x for x in lists if x.name == "eo_cropped")
    assert cropped.list_type == "cropped frequency list"

    # Esperanto has a frequency list, Japanese only a word list.
    frequency_words = {
        x.language: x
        for x in lists
        if x.kind == "frequency_words" and not x.downloaded
    }
    assert "ja" in frequency_words
    assert frequency_words["ja"].list_type == "frequency list"
    assert "eo" not in frequency_words

    # An invalid word list entry is rejected by its own model.
    with pytest.raises(inventory.InventoryError):
        inventory.add_configured(
            tmp_path,
            "lists",
            "bad",
            {"type": "word_list", "language": "eo", "path": "x.txt"},
        )
