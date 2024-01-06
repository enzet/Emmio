from pydantic.main import BaseModel

from emmio.learn.config import LearnConfig
from emmio.lexicon.config import LexiconConfig
from emmio.read.config import ReadConfig


class UserConfig(BaseModel):
    name: str
    learn: dict[str, LearnConfig]
    lexicon: dict[str, LexiconConfig]
    read: dict[str, ReadConfig]
