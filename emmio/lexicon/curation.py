"""Build SFWR curated panels from a frequency list.

A curated panel is a fixed, pre-reviewed subsample of one specific frequency
list version, generalizing the "spine" (`research/metric.tex` "The
log-uniform spine") from one word per stratum to `n_c` per stratum. See
`research/app.md` "Frequency-list curation" for the full design.

Draws `n_c` words per log-uniform stratum (the same partition
`StratifiedSelector` uses), frequency-weighted within the stratum, without
replacement. The draw order is inserted as-is as each word's `panel_order`:
a frequency-weighted draw without replacement already returns its results
in random order, so no separate shuffle step is needed — this matters,
since `panel_order` is what makes a per-learner uniform random draw over
"remaining unanswered panel words" statistically valid (see the 2026-07-31
research note in `research/metric.tex`).

Drawn words get `category = 'U'` (unknown) and are left for human curators
to review — this module never guesses a category itself.
"""

import logging

import numpy as np

from emmio.dictionary.core import DictionaryCollection
from emmio.language import Language
from emmio.lexicon.core import (
    PROPER_NOUN_CAP_RATIO_THRESHOLD,
    _stratum_bounds_of_size,
)
from emmio.lists.frequency_list import FrequencyList

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_N_STRATA: int = 10
DEFAULT_N_C: int = 50


async def classify_automatically(
    word: str,
    language: Language,
    alphabet: str | None,
    frequency_list: FrequencyList | None,
    non_proper_nouns: frozenset[str],
    dictionaries: DictionaryCollection,
) -> str | None:
    """Get an automatic `curated_words.category` code, or `None`.

    Shared by `emmio curate` and the curation API's "next word" endpoint to
    decide which panel words to skip without ever writing anything — the
    whole point of curation is to save human judgment for words these
    checks cannot resolve, so nothing here is cached; it is simply
    recomputed every time. A word outside the language's alphabet or with
    a `cap_ratio` past the proper-noun threshold is assumed "not a
    word"/"proper noun" the same way raw (uncurated) lexicon checking
    already assumes them (see `LexiconChecker.do_skip`); dictionary
    evidence resolves the rest — at least one non-junk entry means "real
    word", all-junk means "not a word".

    :param word: the word to classify
    :param language: the word's language
    :param alphabet: `language.get_symbols()`; `None` disables that check
    :param frequency_list: source of `cap_ratio`; `None` disables the
        proper-noun check
    :param non_proper_nouns: honorific/common-noun exceptions to the
        proper-noun check, e.g. `NON_PROPER_NOUNS.get(language.get_code())`
    :param dictionaries: dictionaries to consult (typically just Kaikki)
    :return: a category code, or `None` if the word is genuinely
        undecidable and needs a human curator
    """
    if alphabet and any(symbol not in alphabet for symbol in word):
        return "N"

    if (
        frequency_list is not None
        and (cap_ratio := frequency_list.get_cap_ratio(word)) is not None
        and cap_ratio > PROPER_NOUN_CAP_RATIO_THRESHOLD
        and word not in non_proper_nouns
    ):
        return "P"

    items = await dictionaries.get_items(word, language)
    if items and any(
        not item.get_commonality(language).is_confirmed_junk() for item in items
    ):
        # At least one entry is not confirmed junk: a real word.
        return "W"
    if items and all(
        item.get_commonality(language).is_confirmed_junk() for item in items
    ):
        # Every entry is confirmed junk (e.g. a bare letter): not a word,
        # the same assumption `AnswerType.ASSUME__NOT_A_WORD__DICTIONARY`
        # makes for raw lexicon checking.
        return "N"

    return None


def draw_stratum_words(
    words: list[str], counts: list[int], n_c: int, rng: np.random.Generator
) -> list[str]:
    """Draw up to `n_c` words from one stratum, weighted, without replacement.

    :param words: the stratum's words, in rank order
    :param counts: parallel occurrence counts
    :param n_c: target sample size; the whole stratum is returned if smaller
    :param rng: random generator (passed in so a run is reproducible with a
        fixed seed, and so multiple strata do not share a global RNG state)
    :return: the drawn words, already in random order (a weighted draw
        without replacement is not returned in rank order) — this order is
        what gets stored as `panel_order`
    """
    if len(words) <= n_c:
        order = rng.permutation(len(words))
        return [words[i] for i in order]

    total: int = sum(counts)
    probabilities: list[float] = [count / total for count in counts]
    indices = rng.choice(len(words), size=n_c, replace=False, p=probabilities)
    return [words[i] for i in indices]


def build_panel(
    frequency_list: FrequencyList,
    n_strata: int,
    n_c: int,
    seed: int | None,
    existing: dict[int, set[str]] | None = None,
) -> list[tuple[str, int, int, str]]:
    """Compute the words needed to bring every stratum up to `n_c` words.

    `n_c` is a target size, not a per-call draw count: a stratum that
    already has `existing` words only gets `n_c - len(existing)` new ones,
    drawn from the words not already present. A stratum already at or past
    target is left untouched, so calling this again with the same `n_c` is
    idempotent, and calling it with a larger `n_c` tops strata up rather
    than redrawing them from scratch. Already-curated words are never
    removed, even if `n_c` is later lowered.

    :param frequency_list: the source list to draw from
    :param n_strata: number of log-uniform strata K
    :param n_c: target words per stratum
    :param seed: random seed, for a reproducible draw; `None` for a fresh
        draw each run
    :param existing: words already curated, keyed by stratum; excluded from
        the draw pool and counted toward that stratum's target
    """
    rng: np.random.Generator = np.random.default_rng(seed)
    words: list[str] = frequency_list.get_words()
    bounds: list[tuple[int, int]] = _stratum_bounds_of_size(
        len(words), n_strata
    )
    existing = existing or {}

    entries: list[tuple[str, int, int, str]] = []
    for stratum, (lo, hi) in enumerate(bounds):
        stratum_existing: set[str] = existing.get(stratum, set())
        needed: int = n_c - len(stratum_existing)
        if needed <= 0:
            logger.info(
                "Stratum %d: already has %d/%d words, skipping.",
                stratum,
                len(stratum_existing),
                n_c,
            )
            continue

        stratum_words: list[str] = [
            word
            for word in words[lo - 1 : hi - 1]
            if word not in stratum_existing
        ]
        stratum_counts: list[int] = [
            frequency_list.get_occurrences(word) for word in stratum_words
        ]
        drawn: list[str] = draw_stratum_words(
            stratum_words, stratum_counts, needed, rng
        )
        entries.extend(
            (word, stratum, len(stratum_existing) + panel_order, "bootstrap")
            for panel_order, word in enumerate(drawn)
        )
        logger.info(
            "Stratum %d: %d new word(s) drawn (%d existing + %d new "
            "towards target %d).",
            stratum,
            len(drawn),
            len(stratum_existing),
            len(drawn),
            n_c,
        )

    return entries
