from pydantic.main import BaseModel

from emmio.language import LanguageConfig


class LexiconConfig(BaseModel):
    file_name: str
    """Path to the lexicon JSON file."""

    language: LanguageConfig
    """Language of the lexicon."""

    frequency_list: str
    """Frequency list used to check lexicon."""

    dictionaries: list[dict] = []
    """Dictionary usage configurations."""
