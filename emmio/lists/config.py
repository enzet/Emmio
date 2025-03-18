"""Configuration of lists."""

from enum import Enum

from pydantic import BaseModel

from emmio.language import LanguageConfig


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
