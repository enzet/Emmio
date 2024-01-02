from pydantic.main import BaseModel

from emmio.language import LanguageConfig


class DictionaryConfig(BaseModel):
    file_name: str
    """Name of the file with dictionary."""

    name: str
    """Dictionary name."""

    from_language: LanguageConfig
    to_language: LanguageConfig
