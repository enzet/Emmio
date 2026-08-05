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

NON_PROPER_NOUNS: dict[str, frozenset[str]] = {
    code: frozenset(words)
    for code, words in _load("non_proper_nouns.json").items()
}
"""Map each language code to words that are frequently capitalized but are
not proper nouns (honorific titles, fragments of multi-word proper nouns like
French `unis` in `les États-Unis`, etc.).

Curated exceptions to the `cap_ratio`-based proper-noun heuristic used by
`freqlist` and by `LexiconChecker`'s automatic not-a-word assumption (see
`emmio.lexicon.core`). Case-folded, lowercase, matching `freqlist`'s output.
"""

CAP_RATIO_UNSUPPORTED_LANGUAGES: frozenset[str] = frozenset({"de"})
"""Codes of languages where mid-sentence capitalization does not signal a
proper noun, so the `cap_ratio`-based heuristic must not be applied.

German capitalizes every noun, common or proper, so a high `cap_ratio` there
means nothing (mirrors `proper_nouns_supported` in `rust/src/main.rs`, which
gates the Rust tool's own diagnostics the same way). Languages with no case
distinction at all (Chinese, Georgian, Japanese, etc.) do not need an entry
here: `cap_ratio` is naturally near 0 or `None` for them, since no word ever
appears titlecased, so the heuristic is already harmless without this list.
"""
