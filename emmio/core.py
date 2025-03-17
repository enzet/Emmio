import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Self

from pydantic import BaseModel


class Record(BaseModel, ABC):
    """An abstraction for a record of actions."""

    time: datetime
    """Time of the response."""

    request_time: datetime | None = None
    """Time of the request."""

    @abstractmethod
    def get_symbol(self) -> str:
        """Get short symbol for the record."""
        raise NotImplementedError()


class Session:
    """User session.

    Relatively short period of time when user is interacting with the
    application in a particular way: learning, testing, etc.
    """

    def end_session(self, time: datetime, actions: int) -> None:
        """Mark session as finished at the specified time.

        :param time: time when session was finished
        :param actions: number of actions performed during the session
        """
        raise NotImplementedError()

    def get_start(self) -> datetime:
        """Get the time when session was started."""
        raise NotImplementedError()

    def get_end(self) -> datetime | None:
        """Get the time when session was finished."""
        raise NotImplementedError()


class ArtifactData(ABC):
    """A manager for data of a particular artifact."""

    @classmethod
    @abstractmethod
    def from_config(cls, path: Path) -> Self:
        """Create an artifact data manager from the configuration file.

        :param path: path to the artifact data directory; if the directory
            does not contain a `config.json` file, an empty dictionary will be
            returned
        """
        raise NotImplementedError()

    @staticmethod
    def read_config(path: Path) -> dict:
        """Read the configuration file.

        :param path: path to the configuration file
        :return: configuration
        """
        if not path.exists():
            if path.parent.exists():
                path.mkdir()
                return {}
            else:
                logging.fatal("`%s` doesn't exist.", path.parent)
                raise FileExistsError()
        else:
            with (path / "config.json").open(encoding="utf-8") as config_file:
                return json.load(config_file)
