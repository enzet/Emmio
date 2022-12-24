from pydantic.main import BaseModel

from emmio.language import LanguageConfig


class LexiconConfig(BaseModel):

    file_name: str
    language: LanguageConfig
    frequency_list: str

    dictionaries: list[dict] = []
    """Dictionary usage configurations."""
