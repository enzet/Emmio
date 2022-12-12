from enum import Enum
from pathlib import Path

from pydantic.main import BaseModel

from emmio.language import LanguageConfig


class DictionaryType(Enum):
    EN_WIKTIONARY = "en_wiktionary"
    FILE = "file"


class DictionaryConfig(BaseModel):

    path: Path
    from_language: LanguageConfig
    to_language: LanguageConfig
