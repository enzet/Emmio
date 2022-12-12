from enum import Enum
from pathlib import Path

from pydantic.main import BaseModel

from emmio.language import LanguageConfig


class SentencesType(Enum):
    TATOEBA = "tatoeba"
    FILE = "file"


class SentencesConfig(BaseModel):
    type: SentencesType
    language_1: LanguageConfig
    language_2: LanguageConfig
    path: Path | None = None
