"""Dictionaries: mappings from word forms to definitions or translations.

Dictionary is a mapping from the word form to its definitions or translations to
other languages. Dictionaries may be represented by files or be used through
API.
"""

import json
from pathlib import Path

with (Path(__file__).parent / "config.json").open(
    encoding="utf-8"
) as config_file:
    CONFIG: dict[str, list[str]] = json.load(config_file)
