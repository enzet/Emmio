"""Regenerate the static per-source language catalogs.

Emmio offers a language for lexicon creation when its artifacts *can be*
downloaded, not only when they are already on disk. The downloadable-language
sets for FrequencyWords and Tatoeba are stable enough to ship statically; this
script rebuilds them from upstream into `emmio/data/`:

- `frequency_words.json` — `{code: year}`, the best FrequencyWords release year
  for each language (2018 preferred, 2016 fallback), taken from the project's
  `content/<year>/<code>/<code>_full.txt` files.
- `tatoeba.json` — sorted list of codes with a per-language Tatoeba sentence
  export.

Only two-letter ISO codes that Emmio knows (`KnownLanguages`) are kept, since a
lexicon can only be created for a fully-defined language.

Usage:

    python scripts/generate_catalogs.py
"""

import json
import logging
import re
from pathlib import Path

import requests
from iso639 import Lang

from emmio.dictionary.en_wiktionary import kaikki_language_name
from emmio.language import KnownLanguages

logger: logging.Logger = logging.getLogger(__name__)

DATA_DIRECTORY: Path = Path(__file__).parent.parent / "emmio" / "data"

GITHUB_TREE_URL: str = (
    "https://api.github.com/repos/hermitdave/FrequencyWords/"
    "git/trees/master?recursive=1"
)
TATOEBA_INDEX_URL: str = "https://downloads.tatoeba.org/exports/per_language/"


def _kaikki_words_url(name: str) -> str:
    """URL of the kaikki.org words file for a language, as Emmio fetches it."""
    return (
        f"https://kaikki.org/dictionary/{name}/words/"
        f"kaikki.org-dictionary-{name.replace(' ', '')}-words.jsonl"
    )


def _two_letter_code(code: str) -> str | None:
    """Map an upstream language code to a two-letter ISO 639-1 code, or `None`.

    Handles both two-letter (`cs`) and three-letter (`ces`) inputs, and skips
    codes with no two-letter form or regional variants (e.g. `pt_br`).
    """
    try:
        language: Lang = Lang(code)
    except Exception:  # noqa: BLE001  # `iso639` raises several types.
        return None
    return language.pt1 or None


def generate_frequency_words(known: set[str]) -> dict[str, int]:
    """Build the FrequencyWords `{code: best year}` catalog from the tree."""
    tree: list[dict] = requests.get(GITHUB_TREE_URL, timeout=60).json()["tree"]
    pattern: re.Pattern[str] = re.compile(
        r"content/(?P<year>2016|2018)/(?P<code>[^/]+)/(?P=code)_full\.txt$"
    )
    years: dict[str, int] = {}
    for entry in tree:
        match: re.Match | None = pattern.match(entry["path"])
        if match is None:
            continue
        code: str | None = _two_letter_code(match["code"])
        if code is None or code not in known:
            continue
        year: int = int(match["year"])
        # Keep the most recent year available for each language.
        if year > years.get(code, 0):
            years[code] = year
    return dict(sorted(years.items()))


def generate_tatoeba() -> list[str]:
    """Build the sorted Tatoeba language catalog from the export index.

    Keyed on each known language's ISO 639-3 code (`get_part3`), exactly as
    `download_tatoeba` names the files it fetches and `get_supported_languages`
    detects them, so the catalog reflects what Emmio can actually download (e.g.
    Chinese `zho` and Norwegian `nor` are absent from Tatoeba, which uses `cmn`
    and `nob`).
    """
    html: str = requests.get(TATOEBA_INDEX_URL, timeout=60).text
    directories: set[str] = set(re.findall(r'href="([a-z]{3})/"', html))
    return sorted(
        language.get_code()
        for language in KnownLanguages.get_languages()
        if language.get_part3() in directories
    )


def generate_kaikki() -> list[str]:
    """Build the sorted Kaikki language catalog by probing kaikki.org.

    A HEAD request per known language (with an alphabet) against the exact words
    URL `EnglishWiktionaryKaikki` downloads, so the catalog reflects what Emmio
    can actually fetch. Languages kaikki.org has no English-Wiktionary
    extraction for are left out.
    """
    codes: list[str] = []
    for language in KnownLanguages.get_languages():
        if not language.has_symbols():
            continue
        url: str = _kaikki_words_url(kaikki_language_name(language))
        try:
            response: requests.Response = requests.head(
                url, timeout=60, allow_redirects=True
            )
        except requests.RequestException:
            continue
        if response.status_code == requests.codes.ok:
            codes.append(language.get_code())
    return sorted(codes)


def main() -> None:
    """Regenerate both catalogs into `emmio/data/`."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    known: set[str] = {
        language.get_code() for language in KnownLanguages.get_languages()
    }
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    frequency_words: dict[str, int] = generate_frequency_words(known)
    (DATA_DIRECTORY / "frequency_words.json").write_text(
        json.dumps(frequency_words, indent=4, ensure_ascii=False) + "\n"
    )
    logger.info("Wrote %d FrequencyWords languages.", len(frequency_words))

    tatoeba: list[str] = generate_tatoeba()
    (DATA_DIRECTORY / "tatoeba.json").write_text(
        json.dumps(tatoeba, indent=4, ensure_ascii=False) + "\n"
    )
    logger.info("Wrote %d Tatoeba languages.", len(tatoeba))

    kaikki: list[str] = generate_kaikki()
    (DATA_DIRECTORY / "kaikki.json").write_text(
        json.dumps(kaikki, indent=4, ensure_ascii=False) + "\n"
    )
    logger.info("Wrote %d Kaikki languages.", len(kaikki))


if __name__ == "__main__":
    main()
