"""Configuration of lists."""

import re
from enum import Enum

from pydantic import BaseModel

from emmio.language import LanguageConfig


class ListUsageConfig(BaseModel):
    """Configuration of lists."""

    id: str
    """Identifier of the list."""

    language: LanguageConfig | None = None
    """Language of the list."""

    year: int | None = None
    """Year of the list."""

    curated: bool = False
    """Whether to draw only from this list's curated panel.

    When set, a lexicon may only draw words the curation consensus has
    confirmed real (`curated_words.category = 'W'`) for `(language, id/year)`
    via `frequency_list_identifier`, instead of the raw list — see
    `CuratedStratifiedSelector`. Only `stratified` selection supports this:
    the panel is a small, fixed sample, not a rankable full list, so the
    other strategies have nothing to rank or threshold against.
    """


def frequency_list_identifier(config: ListUsageConfig) -> str:
    """Get the canonical string identifying one frequency list version.

    This is what `curated_lists.frequency_list_id` is keyed on. For the two
    self-describing sources — `frequency_words` (downloaded) and
    `opensubtitles` (self-generated via `freqlist`) — it is
    `<language>_<id>_<year>`, matching the file naming convention and what
    `emmio data build-panel` already constructs by hand. For a list
    configured by hand in `list_configs`, `id` alone is already a stable,
    unique identifier, so it is returned as-is.
    """
    if (
        config.id in ("frequency_words", "opensubtitles")
        and config.language is not None
        and config.year is not None
    ):
        return f"{config.language}_{config.id}_{config.year}"
    return config.id


def parse_frequency_list_identifier(
    frequency_list_id: str, language: str
) -> ListUsageConfig:
    """Reconstruct a `ListUsageConfig` from its canonical identifier.

    The inverse of `frequency_list_identifier`: tries `<language>_<kind>_
    <year>` for the two self-describing sources first, falling back to
    treating the whole identifier as a bare configured-list `id` (no
    language/year) when that does not match — the same two cases
    `frequency_list_identifier` itself distinguishes.
    """
    match = re.fullmatch(
        rf"{re.escape(language)}_(?P<kind>frequency_words|opensubtitles)_"
        r"(?P<year>\d+)",
        frequency_list_id,
    )
    if match is not None:
        return ListUsageConfig(
            id=match["kind"], language=language, year=int(match["year"])
        )
    return ListUsageConfig(id=frequency_list_id)


class FrequencyListFileFormat(Enum):
    """File format of the frequency list."""

    CSV = "csv"
    """File with CSV format."""

    JSON = "json"
    """File with format `[[word, occurrences]]`."""

    LIST = "list"
    """File with lines `word occurrences`."""


class FrequencyListConfig(BaseModel):
    """Configuration of the word list or frequency list."""

    name: str | None = None
    """Name of the list, e.g. "WortSchatz Esperanto 2011 Literature 10K"."""

    source: str | None = None
    """Source of the list.

    E.g. "https://wortschatz.uni-leipzig.de/en/download/Esperanto".
    """

    file_format: FrequencyListFileFormat
    """Format of the file."""

    language: LanguageConfig
    """Language of the list. E.g. Esperanto."""

    path: str
    """Path to the file."""

    url: str | None = None
    """URL from which the file can be downloaded."""

    csv_delimiter: str = ","
    """Delimiter of the CSV file, if `file_format` is `CSV`."""

    csv_header: list[str] = ["word", "count"]
    """Header of the CSV file, if `file_format` is `CSV`.

    The header should contain columns `word` and `count`.
    """

    is_stripped: bool
    """False for a full frequency list for some text or corpus."""


class WordListConfig(BaseModel):
    """Configuration of the word list or frequency list."""

    name: str
    """Name of the list, e.g. "Jack Personal's Unknown Word List"."""

    source: str
    """Source of the list.

    E.g. "personal knowledge".
    """

    language: LanguageConfig
    """Language of the list. E.g. Esperanto."""

    path: str
    """Path to the file."""
