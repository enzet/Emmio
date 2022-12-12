from pydantic.main import BaseModel

from emmio.learn.config import LearnConfig
from emmio.lexicon.config import LexiconConfig


class UserConfig(BaseModel):
    name: str
    learn: dict[str, LearnConfig]
    lexicon: dict[str, LexiconConfig]
