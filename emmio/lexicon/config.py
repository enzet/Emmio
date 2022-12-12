from pydantic.main import BaseModel

from emmio.language import LanguageConfig


class LexiconConfig(BaseModel):

    path: str
    language: LanguageConfig
    frequency_list: str
