r"""Bootstrap an SFWR curated panel from a raw frequency list.

Given a frequency list file, splits it into `n_strata` log-uniform strata
(the same partition `StratifiedSelector` uses) and draws `n_c` words per
stratum, frequency-weighted within the stratum, without replacement. The
draw order is inserted as-is as each word's `panel_order`: a
frequency-weighted draw without replacement already returns its results in
random order, so no separate shuffle step is needed.

Inserted words get `category = 'U'` (unknown) and are left for human
curators to review — this script never guesses a category itself; see
`research/app.md` "Frequency-list curation" for the full design.

Usage:

    python scripts/build_curated_panel.py \\
        --language fr --frequency-list-id fr_frequency_words_2018 \\
        --input ~/.emmio/lists/fr_frequency_words_2018.txt \\
        --name "French OpenSubtitles 2018 Curated"

Safe to re-run: `add_curated_words` is idempotent, so a repeat run does not
reset words already curated, and only fills in any strata still short of
`n_c` (e.g. after raising `--n-c` on an existing list).
"""

import argparse
import logging
from pathlib import Path

import numpy as np

from emmio import postgres
from emmio.lexicon.core import _stratum_bounds_of_size
from emmio.lists.config import FrequencyListConfig, FrequencyListFileFormat
from emmio.lists.frequency_list import FrequencyList

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_N_STRATA: int = 10
DEFAULT_N_C: int = 50


def load_frequency_list(path: Path, language: str) -> FrequencyList:
    """Load a raw `word count [cap_ratio]` frequency list file."""

    return FrequencyList.from_file(
        path.parent,
        FrequencyListConfig(
            path=path.name,
            file_format=FrequencyListFileFormat.LIST,
            language=language,
            is_stripped=False,
        ),
        path,
    )


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
    frequency_list: FrequencyList, n_strata: int, n_c: int, seed: int | None
) -> list[tuple[str, int, int, str]]:
    """Compute the bootstrap panel: (word, stratum, panel_order, reason).

    :param frequency_list: the source list to draw from
    :param n_strata: number of log-uniform strata K
    :param n_c: target words per stratum
    :param seed: random seed, for a reproducible draw; `None` for a fresh
        draw each run
    """
    rng: np.random.Generator = np.random.default_rng(seed)
    words: list[str] = frequency_list.get_words()
    bounds: list[tuple[int, int]] = _stratum_bounds_of_size(
        len(words), n_strata
    )

    entries: list[tuple[str, int, int, str]] = []
    for stratum, (lo, hi) in enumerate(bounds):
        stratum_words: list[str] = words[lo - 1 : hi - 1]
        stratum_counts: list[int] = [
            frequency_list.get_occurrences(word) for word in stratum_words
        ]
        drawn: list[str] = draw_stratum_words(
            stratum_words, stratum_counts, n_c, rng
        )
        entries.extend(
            (word, stratum, panel_order, "bootstrap")
            for panel_order, word in enumerate(drawn)
        )
        logger.info(
            "Stratum %d: %d/%d words drawn (stratum has %d).",
            stratum,
            len(drawn),
            n_c,
            len(stratum_words),
        )

    return entries


def main() -> None:
    """Build (or extend) a curated panel from a frequency list file."""

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--language", required=True, help="language code")
    parser.add_argument(
        "--frequency-list-id",
        required=True,
        help="identifier for the source list, e.g. fr_frequency_words_2018",
    )
    parser.add_argument(
        "--input", required=True, type=Path, help="frequency list file"
    )
    parser.add_argument(
        "--name",
        required=True,
        help='display name, e.g. "French OpenSubtitles 2018 Curated"',
    )
    parser.add_argument(
        "--n-strata",
        type=int,
        default=DEFAULT_N_STRATA,
        help=f"number of log-uniform strata (default {DEFAULT_N_STRATA})",
    )
    parser.add_argument(
        "--n-c",
        type=int,
        default=DEFAULT_N_C,
        help=f"target words per stratum (default {DEFAULT_N_C})",
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="random seed (default: none)"
    )
    arguments: argparse.Namespace = parser.parse_args()

    frequency_list: FrequencyList = load_frequency_list(
        arguments.input, arguments.language
    )
    logger.info("Loaded `%s`: %d words.", arguments.input, len(frequency_list))

    entries = build_panel(
        frequency_list, arguments.n_strata, arguments.n_c, arguments.seed
    )

    list_id: int = postgres.create_curated_list(
        arguments.language,
        arguments.frequency_list_id,
        arguments.name,
        arguments.n_strata,
    )
    postgres.add_curated_words(list_id, entries)
    logger.info(
        "Curated list %r (id %d): %d candidate words inserted "
        "(existing words were left untouched).",
        arguments.name,
        list_id,
        len(entries),
    )


if __name__ == "__main__":
    main()
