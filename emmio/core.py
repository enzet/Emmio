import json
import logging
from datetime import datetime
from pathlib import Path


class Record:
    """"""

    def get_time(self) -> datetime:
        """Get the time when user response was received."""
        raise NotImplementedError()

    def get_request_time(self) -> datetime:
        """Get the time when questioning was started."""
        raise NotImplementedError()


class Session:
    """"""

    def end_session(self, time: datetime, actions: int) -> None:
        raise NotImplementedError()

    def get_start(self) -> datetime:
        raise NotImplementedError()

    def get_end(self) -> datetime:
        raise NotImplementedError()


class ArtifactData:
    @classmethod
    def from_config(cls, path: Path) -> "ArtifactData":
        raise NotImplementedError()

    @staticmethod
    def read_config(path: Path) -> dict:
        if not path.exists():
            if path.parent.exists():
                path.mkdir()
                return {}
            else:
                logging.fatal(f"{path.parent} doesn't exist.")
                raise FileExistsError()
        else:
            with (path / "config.json").open() as config_file:
                return json.load(config_file)
