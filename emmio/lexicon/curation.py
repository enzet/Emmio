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

import json
import logging
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np

from emmio import postgres
from emmio.catalog import CAP_RATIO_UNSUPPORTED_LANGUAGES
from emmio.dictionary.config import DictionaryUsageConfig
from emmio.dictionary.core import DictionaryCollection, DictionaryItem
from emmio.language import KnownLanguages, Language
from emmio.lexicon.core import (
    PROPER_NOUN_CAP_RATIO_THRESHOLD,
    _stratum_bounds_of_size,
)
from emmio.lists.config import (
    ListUsageConfig,
    frequency_list_identifier,
    parse_frequency_list_identifier,
)
from emmio.lists.frequency_list import FrequencyList
from emmio.sentence.config import SentencesUsageConfig
from emmio.sentence.core import SentenceAndTranslations

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_N_STRATA: int = 10
DEFAULT_N_C: int = 50

EMMIO_CURATOR_USER_ID: str = "emmio"
"""Login of the synthetic curator `classify_automatically` votes as.

Unlike a normal account, it is created with no password (see
`postgres.ensure_user`), so nothing can log in as it — it exists purely as
an attributable `curator_id`, exactly as auditable and overridable by a
later human vote as any other curator's (see `postgres.record_curation_vote`'s
"mode of each curator's latest vote" consensus). This is what keeps
auto-curation from breaking the "only human decisions are stored" rule:
the rule was always about attribution, not about excluding automatic
evidence outright — a vote from a real, visible, named account is exactly
as legitimate as one from a person, it just happens to be Emmio's.
"""

EMMIO_CURATOR_NAME: str = "Emmio"

CLAUDE_CURATOR_USER_ID: str = "claude"
"""Login of the LLM curator `curation/apply_votes.py` votes as.

Same attribution model as `EMMIO_CURATOR_USER_ID`: a real, visible,
password-less account, not a hidden default — see that constant's
docstring for why this doesn't break the "only human decisions are stored"
rule.
"""

CLAUDE_CURATOR_NAME: str = "Claude"


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
        proper-noun check (also disabled outright for a language in
        `CAP_RATIO_UNSUPPORTED_LANGUAGES`, e.g. German, where mid-sentence
        capitalization does not distinguish proper nouns from common ones)
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
        and language.get_code() not in CAP_RATIO_UNSUPPORTED_LANGUAGES
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
    n_c: int | dict[int, int],
    seed: int | None,
    existing: dict[int, set[str]] | None = None,
) -> list[tuple[str, int, int, str]]:
    """Compute the words needed to bring every stratum up to a target size.

    The target is a size, not a per-call draw count: a stratum that already
    has `existing` words only gets `target - len(existing)` new ones, drawn
    from the words not already present. A stratum already at or past target
    is left untouched, so calling this again with the same target is
    idempotent, and calling it with a larger one tops strata up rather than
    redrawing them from scratch. Already-curated words are never removed,
    even if the target is later lowered.

    :param frequency_list: the source list to draw from
    :param n_strata: number of log-uniform strata K
    :param n_c: target words per stratum, either the same for every stratum
        (an absolute target, e.g. the "Build a panel" form) or given per
        stratum (e.g. `existing + 50` for every stratum, the "Extend"
        button's additive semantics regardless of how uneven the strata
        already are); a stratum missing from the mapping targets 0 (no
        further draw)
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
        target: int = n_c if isinstance(n_c, int) else n_c.get(stratum, 0)
        needed: int = target - len(stratum_existing)
        if needed <= 0:
            logger.info(
                "Stratum %d: already has %d/%d words, skipping.",
                stratum,
                len(stratum_existing),
                target,
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
            target,
        )

    return entries


class CuratedPanelResult(NamedTuple):
    """Outcome of `build_or_extend_curated_panel` or `extend_curated_panel`."""

    list_id: int
    name: str
    frequency_list_id: str
    n_strata: int
    new_words: int
    strata_mismatch: bool
    """Whether an existing list's stratum count overrode the requested one.

    The requested `n_strata` is ignored (not an error) so stratum
    boundaries stay consistent with words already curated; the caller
    decides whether/how to surface this.
    """


class CuratedPanelError(ValueError):
    """Raised when a curated panel cannot be built (bad language/list)."""


def build_or_extend_curated_panel(
    data: Any,
    language: Language,
    kind: str,
    year: int,
    name: str | None,
    n_strata: int,
    n_c: int,
    seed: int | None,
) -> CuratedPanelResult:
    """Build or extend an SFWR curated panel from a frequency list.

    Shared by the CLI (`emmio data build-panel`) and the curation web API,
    so both stay backed by one implementation. `n_c` is a per-stratum
    target, not a per-call draw count: see `build_panel`.

    Draws the frequency list via the normal discovery mechanism
    (`Data.get_frequency_list`, the same one `emmio lexicon` uses): for
    `frequency_words` this downloads on demand if not already cached; for
    `opensubtitles` (Emmio-generated, no catalog to download from) the
    source file must already exist locally.

    :param data: the shared `Data`; typed loosely because tests substitute a
        duck-typed stub for `get_data` (mirrors `emmio.api.app._with_kaikki`)
    :param language: the panel's language
    :param kind: `"opensubtitles"` or `"frequency_words"`
    :param year: release/generation year (the caller resolves a default,
        e.g. from `emmio.inventory.frequency_words_year`, if none was given)
    :param name: display name; a default is derived if omitted
    :param n_strata: number of log-uniform strata; ignored in favor of the
        existing list's count if the list already exists (see
        `CuratedPanelResult.strata_mismatch`)
    :param n_c: target words per stratum
    :param seed: random seed, for a reproducible draw; `None` for a fresh
        draw each run
    :raises CuratedPanelError: if no matching frequency list file exists
    """
    list_usage_config = ListUsageConfig(
        id=kind, language=language.get_code(), year=year
    )
    frequency_list: FrequencyList | None = data.get_frequency_list(
        list_usage_config
    )
    if frequency_list is None:
        msg = (
            f"No `{kind}` list for `{language.get_code()}`/{year}. Expected "
            f"`{language.get_code()}_{kind}_{year}.txt` in the lists "
            "directory."
        )
        raise CuratedPanelError(msg)

    frequency_list_id: str = frequency_list_identifier(list_usage_config)
    # Matches the display labels `ListsData.get_frequency_list_options`
    # already uses ("OpenSubtitles (2024)", "FrequencyWords (2018)").
    kind_label: str = {
        "opensubtitles": "OpenSubtitles",
        "frequency_words": "FrequencyWords",
    }[kind]
    resolved_name: str = name or (
        f"{language.get_name()} {kind_label} {year} Curated"
    )

    existing_list_id: int | None = postgres.get_curated_list_id(
        language.get_code(), frequency_list_id
    )
    resolved_n_strata: int = n_strata
    strata_mismatch = False
    existing_by_stratum: dict[int, set[str]] = {}
    if existing_list_id is not None:
        resolved_n_strata = postgres.get_curated_list_n_strata(existing_list_id)
        strata_mismatch = resolved_n_strata != n_strata
        for (
            word,
            stratum,
            _panel_order,
            _category,
            _votes,
            _agreement,
        ) in postgres.get_curated_words(existing_list_id):
            existing_by_stratum.setdefault(stratum, set()).add(word)

    entries: list[tuple[str, int, int, str]] = build_panel(
        frequency_list, resolved_n_strata, n_c, seed, existing_by_stratum
    )
    list_id: int = postgres.create_curated_list(
        language.get_code(), frequency_list_id, resolved_name, resolved_n_strata
    )
    postgres.add_curated_words(list_id, entries)

    return CuratedPanelResult(
        list_id=list_id,
        name=resolved_name,
        frequency_list_id=frequency_list_id,
        n_strata=resolved_n_strata,
        new_words=len(entries),
        strata_mismatch=strata_mismatch,
    )


def extend_curated_panel(
    data: Any,
    list_id: int,
    language: Language,
    frequency_list_id: str,
    extend_by: int,
    seed: int | None = None,
) -> CuratedPanelResult:
    """Extend an existing curated panel by `extend_by` words per stratum.

    Unlike `build_or_extend_curated_panel`'s `n_c` (an absolute per-stratum
    target the caller chooses), this always draws `extend_by` further words
    into every stratum, regardless of how many it already has — the web
    "Extend" button's semantics: strata are not generally even, since a
    small head stratum's population may already be exhausted below the
    original target while learner-driven fallback promotion
    (`postgres.promote_fallback_word`) can push another stratum ahead of
    it, so a single new absolute target could silently do nothing for some
    strata (see `build_panel`'s per-stratum target mapping).

    :param data: the shared `Data`; see `build_or_extend_curated_panel`
    :param list_id: internal identifier of the curated list to extend; the
        caller resolves and validates this (e.g.
        `emmio.api.app._curated_list_id_or_404`), since "no such list" is a
        404 here, not a `CuratedPanelError`
    :param language: the list's language
    :param frequency_list_id: the list's source list identifier, e.g.
        `de_opensubtitles_2024`
    :param extend_by: additional words to draw into every stratum
    :param seed: random seed, for a reproducible draw; `None` for a fresh
        draw each run
    :raises CuratedPanelError: if the list's source frequency list cannot
        be loaded (e.g. an `opensubtitles` file removed after the list was
        built), or `frequency_list_id` is not a `frequency_words`/
        `opensubtitles` identifier (a custom configured list, extended via
        `emmio data build-panel` directly instead)
    """
    list_usage_config: ListUsageConfig = parse_frequency_list_identifier(
        frequency_list_id, language.get_code()
    )
    if list_usage_config.id not in ("frequency_words", "opensubtitles"):
        msg = (
            f"`{frequency_list_id}` is not a `frequency_words`/"
            "`opensubtitles` list; extend it with `emmio data build-panel` "
            "directly."
        )
        raise CuratedPanelError(msg)

    frequency_list: FrequencyList | None = data.get_frequency_list(
        list_usage_config
    )
    if frequency_list is None:
        msg = (
            f"No `{list_usage_config.id}` list for "
            f"`{language.get_code()}`/{list_usage_config.year}."
        )
        raise CuratedPanelError(msg)

    n_strata: int = postgres.get_curated_list_n_strata(list_id)
    existing_by_stratum: dict[int, set[str]] = {}
    for (
        word,
        stratum,
        _panel_order,
        _category,
        _votes,
        _agreement,
    ) in postgres.get_curated_words(list_id):
        existing_by_stratum.setdefault(stratum, set()).add(word)

    targets: dict[int, int] = {
        stratum: len(existing_by_stratum.get(stratum, ())) + extend_by
        for stratum in range(n_strata)
    }

    entries: list[tuple[str, int, int, str]] = build_panel(
        frequency_list, n_strata, targets, seed, existing_by_stratum
    )
    postgres.add_curated_words(list_id, entries)

    list_row: tuple[str, str, str, int] | None = postgres.get_curated_list(
        list_id
    )
    assert list_row is not None
    _language, _frequency_list_id, name, _n_strata = list_row

    return CuratedPanelResult(
        list_id=list_id,
        name=name,
        frequency_list_id=frequency_list_id,
        n_strata=n_strata,
        new_words=len(entries),
        strata_mismatch=False,
    )


class PartialExportResult(NamedTuple):
    """Outcome of `build_partial_export`."""

    list_id: int
    words: int
    """Number of confirmed-real words the export covers."""

    dictionary_entries: int
    """Number of distinct dictionary entries written (may exceed `words`:
    following a word's links, e.g. an inflection, pulls in the linked
    word's own entry too)."""

    sentence_entries: int
    """Number of words with at least one example sentence written."""


class PartialExportError(ValueError):
    """Raised when a partial export cannot be built (no such curated list)."""


def _serialize_dictionary_item(item: DictionaryItem) -> dict[str, Any]:
    """Flatten a (possibly multi-form) `DictionaryItem` into one JSON entry.

    Matches `StructuredDictionary`'s on-disk shape
    (`_structured_item_from_entry` in `emmio.dictionary.core`), which is
    one form per word; Kaikki entries can have several forms (distinct
    senses, e.g. noun and verb), so they are merged here rather than kept
    apart — acceptable loss for a small, supplementary export, not the
    dictionary's own storage format.
    """
    part_of_speech: str | None = None
    transcriptions: set[str] = set()
    definitions: list[str] = []
    links: list[dict[str, str]] = []

    for form in item.get_forms():
        if part_of_speech is None:
            part_of_speech = form.part_of_speech
        transcriptions.update(form.transcriptions)
        # Kaikki only ever fills English definitions (see
        # `EnglishWiktionaryKaikki.process_item`), so no other language's
        # definitions are lost by only exporting this one.
        for definition in form.definitions.get(KnownLanguages.ENGLISH, []):
            definitions.extend(value.value for value in definition.values)
        links.extend(
            {"type": link.link_type, "value": link.link_value}
            for link in form.links
        )

    entry: dict[str, Any] = {}
    if part_of_speech:
        entry["part_of_speech"] = part_of_speech
    if transcriptions:
        entry["transcriptions"] = sorted(transcriptions)
    if definitions:
        entry["definitions"] = {"en": definitions}
    if links:
        entry["links"] = links
    return entry


async def build_partial_export(
    data: Any, curated_list_id: int, max_sentences_per_word: int = 5
) -> PartialExportResult:
    """Precompute a curated list's small dictionary/sentence export.

    Covers only the list's confirmed-real (`category = 'W'`) words — the
    same pool `CuratedStratifiedSelector` draws from
    (`postgres.get_curated_real_words_by_stratum`) — so a curated-list-
    backed lexicon check never needs the full Kaikki/Tatoeba data for the
    language: see `DictionaryData.get_partial_dictionary` and
    `SentencesData.get_partial_sentences`, which load the two files this
    writes (`<dictionaries path>/curated/<list_id>.json`,
    `<sentences path>/curated/<list_id>.json`).

    This is the one place the *full* Kaikki/Tatoeba data is read: it must
    run somewhere those caches already exist (or can be downloaded), e.g.
    a developer machine, not the eventual small-footprint server — the
    server only ever needs this function's output.

    Sentences never carry translations here: lexicon *checking*
    deliberately never shows one (`_sentence_html` in `emmio.api.app`), so
    only the source-language sentence text is exported (see
    `CuratedSentences` in `emmio.sentence.core`).

    :param data: the shared `Data`; typed loosely because tests substitute a
        duck-typed stub for `get_data` (mirrors `build_or_extend_curated_panel`)
    :param curated_list_id: internal identifier of the curated list
    :param max_sentences_per_word: cap on example sentences exported per word
    :raises PartialExportError: if no curated list has this id
    """
    list_row: tuple[str, str, str, int] | None = postgres.get_curated_list(
        curated_list_id
    )
    if list_row is None:
        msg = f"No curated list with id {curated_list_id}."
        raise PartialExportError(msg)
    language_code: str = list_row[0]
    language: Language = Language.from_code(language_code)

    words_by_stratum: dict[int, list[str]] = (
        postgres.get_curated_real_words_by_stratum(curated_list_id)
    )
    words: list[str] = sorted(
        {
            word
            for stratum_words in words_by_stratum.values()
            for word in stratum_words
        }
    )

    dictionaries: DictionaryCollection = data.get_dictionaries(
        [DictionaryUsageConfig(id="kaikki", from_language=language_code)]
    )
    dictionary_entries: dict[str, dict[str, Any]] = {}
    for word in words:
        for _dictionary, item in await dictionaries.get_items_marked(
            word, language
        ):
            if item.word not in dictionary_entries:
                dictionary_entries[item.word] = _serialize_dictionary_item(item)

    sentences_data = data.get_sentences_data()
    sentence_entries: dict[str, list[str]] = {}
    for word in words:
        results: list[SentenceAndTranslations] = sentences_data.get(
            word,
            [SentencesUsageConfig(id="tatoeba", language=language_code)],
            max_number=max_sentences_per_word,
        )
        if results:
            sentence_entries[word] = [
                result.sentence.text for result in results
            ]

    dictionaries_directory: Path = data.dictionaries.path / "curated"
    dictionaries_directory.mkdir(parents=True, exist_ok=True)
    with (dictionaries_directory / f"{curated_list_id}.json").open(
        "w", encoding="utf-8"
    ) as output_file:
        json.dump(
            dictionary_entries,
            output_file,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

    sentences_directory: Path = sentences_data.path / "curated"
    sentences_directory.mkdir(parents=True, exist_ok=True)
    with (sentences_directory / f"{curated_list_id}.json").open(
        "w", encoding="utf-8"
    ) as output_file:
        json.dump(
            sentence_entries,
            output_file,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

    return PartialExportResult(
        list_id=curated_list_id,
        words=len(words),
        dictionary_entries=len(dictionary_entries),
        sentence_entries=len(sentence_entries),
    )
