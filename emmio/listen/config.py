from pathlib import Path

from pydantic import BaseModel


class ListenConfig(BaseModel):
    file_name: Path
    base_language: str
    learning_id: str
    lists: list
    audio_base: list
    audio_learning: list
    dictionaries: list
