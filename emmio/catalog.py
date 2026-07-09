"""Static catalogs of languages whose artifacts can be downloaded.

Emmio offers a language for lexicon creation when its frequency list and
example sentences *can be* downloaded, not only when they are already on disk.
The downloadable-language sets for FrequencyWords and Tatoeba are stable, so
they are shipped as JSON under `emmio/data/` and loaded here once at import.

Regenerate the JSON with `scripts/generate_catalogs.py`.
"""

import json
from pathlib import Path
from typing import Any

_DATA_DIRECTORY: Path = Path(__file__).parent / "data"


def _load(name: str) -> Any:
    """Load a JSON catalog file from `emmio/data/`."""
    return json.loads((_DATA_DIRECTORY / name).read_text())


FREQUENCY_WORDS_YEARS: dict[str, int] = _load("frequency_words.json")
"""Map each language code to the best FrequencyWords release year for it.

E.g. `{"cs": 2018, "th": 2016, ...}`. 2018 is preferred; 2016 is the fallback
for languages the 2018 release does not cover (e.g. Thai, Chinese).
"""

TATOEBA_LANGUAGES: frozenset[str] = frozenset(_load("tatoeba.json"))
"""Codes of languages with a downloadable Tatoeba sentence export."""

KAIKKI_LANGUAGES: frozenset[str] = frozenset(_load("kaikki.json"))
"""Codes of languages with a downloadable Kaikki (en.wiktionary) dictionary."""
