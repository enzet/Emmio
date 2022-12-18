from pydantic.main import BaseModel

from emmio.language import LanguageConfig


class AudioConfig(BaseModel):
    directory_name: str
    format: str
    language: LanguageConfig
