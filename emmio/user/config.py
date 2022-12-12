from pydantic.main import BaseModel

from emmio.lexicon.config import LexiconConfig
from emmio.learn.config import LearnConfig


class UserConfig(BaseModel):
    name: str
    learn: dict[str, LearnConfig]
    lexicon: dict[str, LexiconConfig]
