from pydantic.main import BaseModel

from emmio.language import LanguageConfig


class LexiconConfig(BaseModel):
    file_name: str
    """Path to the lexicon JSON file."""

    language: LanguageConfig
    """Language of the lexicon."""

    selection: str
    """How words was picked."""

    frequency_list: str | None = None
    """Frequency list used to check lexicon."""

    dictionaries: list[dict] = []
    """Dictionary usage configurations."""

    sentences: list[dict] = []
    """Sentences configurations."""

    precision_per_week: int = 0
    """Needed precision for every week.
    
    When rechecking the lexicon, the process will stop, when the needed
    precision will be achieved.
    """
