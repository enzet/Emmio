import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from emmio.lists.core import FrequencyList
from emmio.lists.config import ListsConfig


class DataConfig(BaseModel):
    frequency: dict[str, ListsConfig]


@dataclass
class Data:
    """Registry of all available Emmio data."""

    path: Path
    """Path to directory that contains all data."""

    frequency: dict[str, FrequencyList] = field(default_factory=dict)
    """Collection of all accessible frequency lists."""

    @classmethod
    def from_config(cls, path: Path) -> "Data":

        data: "Data" = cls(path)

        config_path: Path = path / "config.json"

        config: DataConfig
        if not config_path.exists():
            config = DataConfig()
        else:
            with config_path.open() as config_file:
                config = DataConfig(**json.load(config_file))

        for id_, frequency_config in config.frequency:
            data.frequency[id_] = FrequencyList.from_config()

        return data

    def list_frequency(self):
        for id_, frequency_list in self.frequency:
            print(frequency_list.name)


if __name__ == "__main__":
    """"""
