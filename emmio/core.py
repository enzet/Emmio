"""Core functionality."""

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


class Session(BaseModel):
    """User session.

    Relatively short period of time when user is interacting with the
    application in a particular way: learning, testing, etc.
    """

    start: datetime
    """Time when session was started."""

    end: datetime | None = None
    """Time when session was finished."""


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

            logging.fatal("`%s` doesn't exist.", path.parent)
            raise FileExistsError()

        with (path / "config.json").open(encoding="utf-8") as config_file:
            result: dict = json.load(config_file)
            return result
