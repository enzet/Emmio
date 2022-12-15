from pathlib import Path

from pydantic.main import BaseModel

from emmio.language import LanguageConfig


class DictionaryConfig(BaseModel):

    file_name: str
    """Name of the file with dictionary."""

    from_language: LanguageConfig
    to_language: LanguageConfig
