"""Inventory and management of the shared data artifacts.

Answers, for a data directory, "what is downloaded and what could be":
Kaikki dictionaries, Tatoeba sentence exports, and FrequencyWords frequency
lists exist for every known language and are fetched on demand; other
artifacts are the local files configured in each directory's `config.json`.

Listing (`*_artifacts`) only observes the filesystem — it never loads,
constructs, or downloads anything — so it is cheap and safe to run on a live
installation. The management functions (`download_*`, `delete_*`,
`add_configured`, `delete_configured`) do exactly what their names say and
nothing more.
"""

import bz2
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from emmio.catalog import FREQUENCY_WORDS_YEARS
from emmio.data import (
    CONFIGURATION_FILE_NAME,
    DICTIONARIES_DIRECTORY_NAME,
    LISTS_DIRECTORY_NAME,
    SENTENCES_DIRECTORY_NAME,
)
from emmio.dictionary.config import DictionaryConfig
from emmio.dictionary.en_wiktionary import (
    DictionaryDownloadError,
    EnglishWiktionaryKaikki,
    kaikki_language_name,
)
from emmio.language import KnownLanguages, Language
from emmio.lists.config import FrequencyListConfig, WordListConfig
from emmio.sentence.config import SentenceConfig
from emmio.util import download

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

ARTIFACT_TYPES: tuple[str, str, str] = (
    DICTIONARIES_DIRECTORY_NAME,
    SENTENCES_DIRECTORY_NAME,
    LISTS_DIRECTORY_NAME,
)

DEFAULT_FREQUENCY_WORDS_YEAR: int = 2018
"""The most recent year the FrequencyWords project has lists for."""


def frequency_words_year(language: Language) -> int:
    """Best FrequencyWords release year for a language.

    Uses the static catalog (e.g. Thai and Chinese only exist in 2016), falling
    back to the most recent release for languages absent from it.
    """
    return FREQUENCY_WORDS_YEARS.get(
        language.get_code(), DEFAULT_FREQUENCY_WORDS_YEAR
    )


# The config field naming the artifact's file, per artifact type.
_FILE_FIELD: dict[str, str] = {
    DICTIONARIES_DIRECTORY_NAME: "file_name",
    SENTENCES_DIRECTORY_NAME: "file_name",
    LISTS_DIRECTORY_NAME: "path",
}
# The model validating a configuration entry, per artifact type.
_CONFIG_MODEL: dict[str, type] = {
    DICTIONARIES_DIRECTORY_NAME: DictionaryConfig,
    SENTENCES_DIRECTORY_NAME: SentenceConfig,
    LISTS_DIRECTORY_NAME: FrequencyListConfig,
}


class InventoryError(Exception):
    """A data artifact operation cannot be performed."""


@dataclass
class Artifact:
    """A shared data artifact the application can use, downloaded or not."""

    name: str
    """Human-readable name, e.g. `Kaikki` or a configured list name."""

    kind: str
    """Source: `kaikki`, `tatoeba`, `frequency_words`, `file`, `database`."""

    language: str | None
    """ISO 639-1 code, or `None` for language-neutral artifacts."""

    downloaded: bool
    """Whether the artifact is present on disk."""

    size: int | None
    """Size on disk in bytes, when downloaded."""

    path: str | None
    """Location relative to the data directory, when downloaded."""

    list_type: str | None = None
    """For list artifacts: `word list`, `frequency list`, or `cropped
    frequency list` (one that does not cover its whole corpus); `None` for
    other artifact types."""


def tree_size(path: Path) -> int:
    """Total size in bytes of a file or of a directory tree."""
    if path.is_file():
        return path.stat().st_size
    return sum(
        file.stat().st_size for file in path.rglob("*") if file.is_file()
    )


def format_size(size: int | None) -> str:
    """Format a byte count as a short human-readable size, e.g. `1.2 GB`."""
    if size is None:
        return "—"
    value: float = float(size)
    units: list[str] = ["B", "kB", "MB", "GB", "TB"]
    index: int = 0
    while value >= 1000 and index < len(units) - 1:
        value /= 1000
        index += 1
    if index == 0:
        return f"{size} B"
    return f"{value:.1f} {units[index]}"


def _read_config(path: Path) -> dict:
    """Read an artifact directory's `config.json`, empty if absent.

    Unlike `ArtifactData.read_config` this never creates directories or raises
    on a missing data directory: the inventory must only observe the disk.
    """
    config_path: Path = path / CONFIGURATION_FILE_NAME
    if not config_path.is_file():
        return {}
    with config_path.open(encoding="utf-8") as config_file:
        return json.load(config_file)


def _artifact(
    name: str,
    kind: str,
    language: str | None,
    base: Path,
    location: Path,
    list_type: str | None = None,
) -> Artifact:
    """Describe an artifact expected at `location` (inside `base`).

    `downloaded` reflects whether anything actually exists there.
    """
    downloaded: bool = location.exists()
    return Artifact(
        name=name,
        kind=kind,
        language=language,
        downloaded=downloaded,
        size=tree_size(location) if downloaded else None,
        path=str(location.relative_to(base)) if downloaded else None,
        list_type=list_type,
    )


def _sort(artifacts: list[Artifact]) -> list[Artifact]:
    """Sort downloaded first, largest first, then by language and name."""
    artifacts.sort(
        key=lambda artifact: (
            not artifact.downloaded,
            -(artifact.size or 0),
            artifact.language or "",
            artifact.name,
        )
    )
    return artifacts


def dictionary_artifacts(base: Path) -> list[Artifact]:
    """List dictionary artifacts, downloaded and available.

    Kaikki (English Wiktionary) dictionaries can be downloaded for any known
    language with an alphabet; a downloaded one is a per-prefix cache
    directory named after the language. File dictionaries come from
    `dictionaries/config.json`.

    :param base: the data directory, usually `~/.emmio`
    """
    directory: Path = base / DICTIONARIES_DIRECTORY_NAME
    artifacts: list[Artifact] = []
    for language in KnownLanguages.get_languages():
        if not language.has_symbols():
            continue
        artifacts.append(
            _artifact(
                "Kaikki",
                "kaikki",
                language.get_code(),
                base,
                directory / "cache" / "kaikki" / kaikki_language_name(language),
            )
        )
    for id_, raw in sorted(_read_config(directory).items()):
        artifacts.append(
            _artifact(
                raw.get("name") or id_,
                "file",
                raw.get("from_language"),
                base,
                directory / raw["file_name"],
            )
        )
    return _sort(artifacts)


def sentence_artifacts(base: Path) -> list[Artifact]:
    """List sentence artifacts, downloaded and available.

    Tatoeba publishes a per-language sentence export for every language; a
    downloaded one is a `<part3>_sentences.tsv[.bz2]` cache file. The links
    database is shared by every language. Sentence collections configured as
    local files come from `sentences/config.json`.

    :param base: the data directory, usually `~/.emmio`
    """
    directory: Path = base / SENTENCES_DIRECTORY_NAME
    artifacts: list[Artifact] = [
        _artifact(
            "Tatoeba sentence database",
            "database",
            None,
            base,
            directory / "sentences.db",
        )
    ]
    for language in KnownLanguages.get_languages():
        plain: Path = (
            directory / "cache" / f"{language.get_part3()}_sentences.tsv"
        )
        compressed: Path = plain.with_name(plain.name + ".bz2")
        artifacts.append(
            _artifact(
                "Tatoeba sentences",
                "tatoeba",
                language.get_code(),
                base,
                plain if plain.exists() else compressed,
            )
        )
    for id_, raw in sorted(_read_config(directory).items()):
        languages: list[str] = raw.get("languages") or []
        artifacts.append(
            _artifact(
                raw.get("name") or id_,
                "file",
                languages[0] if languages else None,
                base,
                directory / raw["file_name"],
            )
        )
    return _sort(artifacts)


def list_artifacts(base: Path) -> list[Artifact]:
    """List word and frequency list artifacts, downloaded and available.

    Three sources: lists (word lists and frequency lists alike) configured in
    `lists/config.json`, downloaded FrequencyWords lists —
    plain `<code>_frequency_words_<year>.txt` files, the same convention
    `ListsData` uses — and, for every known language with no frequency list
    from the first two, the FrequencyWords list Emmio downloads on first use
    (a word list does not stand in for a frequency list).

    :param base: the data directory, usually `~/.emmio`
    """
    directory: Path = base / LISTS_DIRECTORY_NAME
    artifacts: list[Artifact] = []
    covered: set[str] = set()  # Languages with a frequency list already.
    for id_, raw in sorted(_read_config(directory).items()):
        list_type: str
        match raw.get("type"):
            case "frequency_list":
                if language_code := raw.get("language"):
                    covered.add(language_code)
                list_type = (
                    "cropped frequency list"
                    if raw.get("is_stripped")
                    else "frequency list"
                )
            case "word_list":
                list_type = "word list"
            case _:
                continue
        artifacts.append(
            _artifact(
                raw.get("name") or id_,
                "file",
                raw.get("language"),
                base,
                directory / raw["path"],
                list_type=list_type,
            )
        )
    for file_path in sorted(directory.glob("*_frequency_words_*.txt")):
        match: re.Match | None = re.fullmatch(
            r"(?P<language>.+)_frequency_words_(?P<year>\d+)", file_path.stem
        )
        if match is None:
            continue
        covered.add(match["language"])
        artifacts.append(
            _artifact(
                f"FrequencyWords {match['year']}",
                "frequency_words",
                match["language"],
                base,
                file_path,
                list_type="frequency list",
            )
        )
    for language in KnownLanguages.get_languages():
        code: str = language.get_code()
        # Only offer a FrequencyWords download where the project actually has a
        # list (e.g. Latin and Norwegian Bokmål have none).
        if code in covered or code not in FREQUENCY_WORDS_YEARS:
            continue
        artifacts.append(
            Artifact(
                name="FrequencyWords",
                kind="frequency_words",
                language=code,
                downloaded=False,
                size=None,
                path=None,
                list_type="frequency list",
            )
        )
    return _sort(artifacts)


# Downloading on-demand artifacts. Each function returns the artifact's
# location and whether anything was actually fetched (`False` when it was
# already on disk).


def download_kaikki(base: Path, language: Language) -> tuple[Path, bool]:
    """Download a Kaikki dictionary and build its cache.

    Delegates to `EnglishWiktionaryKaikki`, whose constructor downloads the
    kaikki.org JSONL words file and splits it into the per-prefix cache
    directory (the download itself may take minutes for large languages).

    :param base: the data directory, usually `~/.emmio`
    :param language: language of the words being defined
    """
    directory: Path = base / DICTIONARIES_DIRECTORY_NAME
    name: str = kaikki_language_name(language)
    cache: Path = directory / "cache" / "kaikki" / name
    if cache.exists():
        return cache, False
    directory.mkdir(parents=True, exist_ok=True)
    try:
        EnglishWiktionaryKaikki(directory, directory / "cache", language, name)
    except (ValueError, DictionaryDownloadError) as error:
        raise InventoryError(str(error)) from error
    return cache, True


def download_tatoeba(base: Path, language: Language) -> tuple[Path, bool]:
    """Download and unpack a Tatoeba per-language sentence export.

    The same fetch `TatoebaDatabase.load_language` performs implicitly,
    including its guard against Tatoeba's placeholder response for languages
    it has no sentences for; the archive is removed after unpacking.

    :param base: the data directory, usually `~/.emmio`
    :param language: language of the sentences
    """
    cache: Path = base / SENTENCES_DIRECTORY_NAME / "cache"
    plain: Path = cache / f"{language.get_part3()}_sentences.tsv"
    compressed: Path = plain.with_name(plain.name + ".bz2")
    if plain.exists():
        return plain, False
    if compressed.exists():
        return compressed, False

    cache.mkdir(parents=True, exist_ok=True)
    download(
        f"https://downloads.tatoeba.org/exports/per_language/"
        f"{language.get_part3()}/{language.get_part3()}_sentences.tsv.bz2",
        compressed,
    )
    if not compressed.exists():
        message: str = f"Failed to download Tatoeba `{language.get_name()}`."
        raise InventoryError(message)
    # Tatoeba answers with a small placeholder for unknown languages.
    if compressed.stat().st_size < 1000:
        compressed.unlink()
        message = f"Tatoeba has no sentences for `{language.get_name()}`."
        raise InventoryError(message)
    with bz2.open(compressed) as archive, plain.open("wb+") as cache_file:
        cache_file.write(archive.read())
    compressed.unlink()
    return plain, True


def download_frequency_words(
    base: Path, language: Language, year: int
) -> tuple[Path, bool]:
    """Download a FrequencyWords frequency list.

    The same file `FrequencyWordsList.from_short_config` fetches implicitly
    on first use, guarded against GitHub's "404: Not Found" body for
    languages the project has no list for.

    :param base: the data directory, usually `~/.emmio`
    :param language: language of the frequency list
    :param year: year of the FrequencyWords release, e.g. 2018
    """
    directory: Path = base / LISTS_DIRECTORY_NAME
    code: str = language.get_code()
    file_path: Path = directory / f"{code}_frequency_words_{year}.txt"
    if file_path.exists():
        return file_path, False

    directory.mkdir(parents=True, exist_ok=True)
    data: bytearray | None = download(
        f"https://raw.githubusercontent.com/hermitdave/FrequencyWords/"
        f"master/content/{year}/{code}/{code}_full.txt",
        file_path,
    )
    if data is None or not file_path.exists():
        message: str = f"Failed to download FrequencyWords `{code}` for {year}."
        raise InventoryError(message)
    if data.startswith(b"404") or file_path.stat().st_size < 1000:
        file_path.unlink()
        message = f"FrequencyWords has no `{code}` list for {year}."
        raise InventoryError(message)
    return file_path, True


# Deleting artifacts. Each function returns the removed locations and the
# total size in bytes that was freed, and raises `InventoryError` when there
# is nothing to remove.


def delete_kaikki(base: Path, language: Language) -> tuple[list[Path], int]:
    """Delete a downloaded Kaikki dictionary cache.

    :param base: the data directory, usually `~/.emmio`
    :param language: language of the words being defined
    """
    cache: Path = (
        base
        / DICTIONARIES_DIRECTORY_NAME
        / "cache"
        / "kaikki"
        / kaikki_language_name(language)
    )
    if not cache.exists():
        message: str = (
            f"No downloaded Kaikki dictionary for `{language.get_name()}`."
        )
        raise InventoryError(message)
    size: int = tree_size(cache)
    shutil.rmtree(cache)
    return [cache], size


def delete_tatoeba(base: Path, language: Language) -> tuple[list[Path], int]:
    """Delete a downloaded Tatoeba sentence export.

    Only the cache files are removed; sentences already loaded into the
    shared `sentences.db` database stay there.

    :param base: the data directory, usually `~/.emmio`
    :param language: language of the sentences
    """
    cache: Path = base / SENTENCES_DIRECTORY_NAME / "cache"
    plain: Path = cache / f"{language.get_part3()}_sentences.tsv"
    existing: list[Path] = [
        path
        for path in (plain, plain.with_name(plain.name + ".bz2"))
        if path.exists()
    ]
    if not existing:
        message: str = (
            f"No downloaded Tatoeba sentences for `{language.get_name()}`."
        )
        raise InventoryError(message)
    size: int = sum(tree_size(path) for path in existing)
    for path in existing:
        path.unlink()
    return existing, size


def delete_frequency_words(
    base: Path, language: Language, year: int | None
) -> tuple[list[Path], int]:
    """Delete a downloaded FrequencyWords frequency list.

    :param base: the data directory, usually `~/.emmio`
    :param language: language of the frequency list
    :param year: year of the FrequencyWords release; may be omitted when only
        one release is downloaded for the language
    """
    directory: Path = base / LISTS_DIRECTORY_NAME
    code: str = language.get_code()
    if year is not None:
        candidates: list[Path] = [
            directory / f"{code}_frequency_words_{year}.txt"
        ]
        candidates = [path for path in candidates if path.exists()]
    else:
        candidates = sorted(directory.glob(f"{code}_frequency_words_*.txt"))
    if not candidates:
        message: str = f"No downloaded FrequencyWords list for `{code}`."
        raise InventoryError(message)
    if len(candidates) > 1:
        years: str = ", ".join(
            sorted(path.stem.split("_")[-1] for path in candidates)
        )
        message = (
            f"Several FrequencyWords lists for `{code}` are downloaded; "
            f"specify `--year`: {years}."
        )
        raise InventoryError(message)
    size: int = tree_size(candidates[0])
    candidates[0].unlink()
    return candidates, size


# Configured file artifacts: entries in a `config.json` pointing at a local
# file. `add_configured` registers one (without downloading anything);
# `delete_configured` is its inverse and also removes the file.


def _write_config(directory: Path, config: dict) -> None:
    """Write an artifact directory's `config.json`."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / CONFIGURATION_FILE_NAME).open(
        "w", encoding="utf-8"
    ) as config_file:
        json.dump(config, config_file, ensure_ascii=False, indent=4)
        config_file.write("\n")


def add_configured(
    base: Path, type_: str, id_: str, entry: dict
) -> tuple[Path, bool]:
    """Register a file artifact in its directory's `config.json`.

    The entry is validated against the artifact type's configuration model
    before it is written. Nothing is downloaded: the file the entry points at
    is expected to be put in place separately, and the second element of the
    result tells whether it is already there.

    :param base: the data directory, usually `~/.emmio`
    :param type_: artifact type, one of `ARTIFACT_TYPES`
    :param id_: unique identifier for the entry
    :param entry: the configuration entry to store
    :return: the artifact file's path and whether that file exists
    """
    directory: Path = base / type_
    config: dict = _read_config(directory)
    if id_ in config:
        message: str = (
            f"`{id_}` is already configured in `{type_}/config.json`."
        )
        raise InventoryError(message)
    model: type = _CONFIG_MODEL[type_]
    # The `lists` directory holds two kinds of entries, each with its own
    # configuration model.
    if type_ == LISTS_DIRECTORY_NAME and entry.get("type") == "word_list":
        model = WordListConfig
    try:
        model(**entry)
    except ValidationError as error:
        raise InventoryError(str(error)) from error
    config[id_] = entry
    _write_config(directory, config)
    file_path: Path = directory / entry[_FILE_FIELD[type_]]
    return file_path, file_path.exists()


def delete_configured(
    base: Path, id_: str, type_: str | None
) -> tuple[list[Path], int]:
    """Remove a configured artifact: its `config.json` entry and its file.

    :param base: the data directory, usually `~/.emmio`
    :param id_: the entry's identifier
    :param type_: artifact type, one of `ARTIFACT_TYPES`; may be omitted when
        the identifier is unambiguous across types
    :return: the removed file paths (empty if the file was already absent)
        and the total size freed
    """
    types: list[str] = [type_] if type_ else list(ARTIFACT_TYPES)
    found: list[str] = [
        candidate
        for candidate in types
        if id_ in _read_config(base / candidate)
    ]
    if not found:
        message: str = f"No configured artifact `{id_}`."
        raise InventoryError(message)
    if len(found) > 1:
        message = (
            f"`{id_}` is configured in several places: "
            f"{', '.join(found)}; specify `--type`."
        )
        raise InventoryError(message)

    directory: Path = base / found[0]
    config: dict = _read_config(directory)
    entry: dict = config.pop(id_)
    _write_config(directory, config)

    file_path: Path = directory / entry[_FILE_FIELD[found[0]]]
    if not file_path.exists():
        return [], 0
    size: int = tree_size(file_path)
    file_path.unlink()
    return [file_path], size
