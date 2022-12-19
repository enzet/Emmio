"""
This module is for dictionaries.

Dictionary is a mapping from the word form to its definitions or translations to
other languages.  Dictionaries may be represented by files or be used through
API.
"""
import json
from pathlib import Path

with (Path(__file__).parent / "config.json").open() as config_file:
    CONFIG: dict[str, list[str]] = json.load(config_file)
