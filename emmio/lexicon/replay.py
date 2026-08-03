"""Replay the checking process of a real lexicon, simulation-style.

Fetch the chronological answer log of one user's lexicon from the
database, re-run the production rate estimator after every answer (the
same `estimate_rate_with_sd` path the API uses), and write the estimate
trajectory r̂ with its SD to a CSV file; visualize it with::

    python -m emmio.lexicon.visualize replay john_fr_1.csv

Run as::

    python -m emmio.lexicon.replay --user john --lexicon fr_1

The frequency list configured for the lexicon is loaded from the Emmio
data directory (`EMMIO_DATA_DIR`, default `~/.emmio`); the log comes
from PostgreSQL.
"""

import argparse
import csv
import os
from pathlib import Path

from tqdm import tqdm

from emmio.data import Data
from emmio.lexicon.config import LexiconSelection
from emmio.lexicon.core import (
    DEFAULT_N_STRATA,
    LexiconResponse,
    WordStates,
    estimate_rate_with_sd,
)
from emmio.lists.config import ListUsageConfig
from emmio.lists.frequency_list import FrequencyList
from emmio.postgres import get_lexicon_config, get_lexicon_record_log
from emmio.ui import Interface, TerminalInterface


def replay(
    records: list[tuple[str, str]],
    selection: LexiconSelection,
    frequency_list: FrequencyList | None,
    step: int = 1,
    precision: int = 100,
    n_strata: int = DEFAULT_N_STRATA,
    curated_words_by_stratum: dict[int, list[str]] | None = None,
    *,
    show_progress: bool = False,
) -> tuple[list[int], list[tuple[float, float] | None]]:
    """Re-run the production rate estimator over a recorded log.

    Answers are fed to the estimator in their recorded order; at every
    checkpoint the estimator matching the lexicon's selection strategy
    is run on the states collected so far, exactly as the API does after
    a real answer.

    :param records: chronological (word, response code) pairs
    :param selection: the lexicon's stored selection strategy
    :param frequency_list: source of ranks and frequency shares, required
        by every estimator except the frequency one
    :param step: checkpoint spacing in answers
    :param precision: number of "don't know" answers per frequency
        estimator window
    :param n_strata: see `estimate_rate_with_sd`
    :param curated_words_by_stratum: see `estimate_rate_with_sd`
    :param show_progress: draw a terminal progress bar (for the CLI; the
        API replays silently)
    :return: (checkpoint query numbers, per-checkpoint estimates)
    """
    know: str = LexiconResponse.KNOW.to_code()
    know_class: str = LexiconResponse.KNOW_SEMANTIC_CLASS.to_code()
    dont: str = LexiconResponse.DONT.to_code()
    states: WordStates = {}
    sequence: list[int] = []
    checkpoints: list[int] = []
    estimates: list[tuple[float, float] | None] = []

    for number, (word, code) in tqdm(
        enumerate(records, start=1),
        total=len(records),
        disable=not show_progress,
    ):
        states[word] = (code, None)
        if code in (know, know_class):
            sequence.append(1)
        elif code == dont:
            sequence.append(0)
        if number % step != 0 and number != len(records):
            continue
        checkpoints.append(number)
        estimates.append(
            estimate_rate_with_sd(
                selection,
                frequency_list,
                states,
                sequence,
                precision,
                n_strata,
                curated_words_by_stratum,
            )
        )

    return checkpoints, estimates


def write_replay_csv(
    path: Path,
    records: list[tuple[str, str]],
    checkpoints: list[int],
    estimates: list[tuple[float, float] | None],
    selection: LexiconSelection,
) -> None:
    """Write the replayed trajectory to a CSV file, one row per answer.

    Columns: `queries` (1-based answer number), `response` (the
    recorded response code), `checkpoint` (1 where the estimator ran),
    `r_hat` and `sd` (empty where the estimator had no answer or the
    row is not a checkpoint), and `selection` (the lexicon's selection
    strategy, constant).

    :param path: output CSV file
    :param records: chronological (word, response code) pairs
    :param checkpoints: query numbers of the checkpoints
    :param estimates: per-checkpoint (r̂, SD), or None where the
        estimator had no answer
    :param selection: the lexicon's stored selection strategy
    """
    estimate_by_query: dict[int, tuple[float, float] | None] = dict(
        zip(checkpoints, estimates, strict=True)
    )
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(
            ["queries", "response", "checkpoint", "r_hat", "sd", "selection"]
        )
        for number, (_, code) in enumerate(records, start=1):
            is_checkpoint: bool = number in estimate_by_query
            estimate: tuple[float, float] | None = estimate_by_query.get(number)
            r_hat, sd = estimate if estimate else ("", "")
            writer.writerow(
                [number, code, int(is_checkpoint), r_hat, sd, selection]
            )


def main(arguments: list[str] | None = None) -> None:
    """Replay a lexicon's checking process and write the estimates."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0]
    )
    parser.add_argument("--user", required=True, help="user login")
    parser.add_argument("--lexicon", required=True, help="lexicon identifier")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(
            os.environ.get("EMMIO_DATA_DIR", str(Path.home() / ".emmio"))
        ),
        help="Emmio data directory holding the frequency lists",
    )
    parser.add_argument(
        "--step", type=int, default=1, help="checkpoint spacing in answers"
    )
    parser.add_argument(
        "--precision",
        type=int,
        default=100,
        help="full-window unknown count for the frequency estimator",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="output CSV file (default `<user>_<lexicon>.csv`)",
    )
    options: argparse.Namespace = parser.parse_args(arguments)
    interface: Interface = TerminalInterface(use_input=False)

    config: dict | None = get_lexicon_config(options.user, options.lexicon)
    if config is None:
        message: str = (
            f"No lexicon `{options.lexicon}` for user `{options.user}`."
        )
        raise SystemExit(message)
    selection: LexiconSelection = LexiconSelection(config["selection"])

    frequency_list: FrequencyList | None = None
    if config.get("frequency_list"):
        frequency_list = Data.from_directory(
            options.data_dir
        ).get_frequency_list(ListUsageConfig(**config["frequency_list"]))
        if frequency_list is None:
            message = "Configured frequency list could not be loaded."
            raise SystemExit(message)

    records: list[tuple[str, str]] = get_lexicon_record_log(
        options.user, options.lexicon
    )
    if not records:
        interface.print("The lexicon has no records to replay.")
        return
    interface.print(f"{len(records)} records, selection `{selection}`.")

    if frequency_list is not None:
        listed: set[str] = set(frequency_list.get_words())
        outside: set[str] = {word for word, _ in records if word not in listed}
        if outside:
            interface.print(
                f"{len(outside)} checked word(s) are not in the frequency "
                f"list and are invisible to the estimator."
            )

    checkpoints, estimates = replay(
        records,
        selection,
        frequency_list,
        options.step,
        options.precision,
        show_progress=True,
    )

    last: tuple[float, float] | None = next(
        (estimate for estimate in reversed(estimates) if estimate is not None),
        None,
    )
    if last is None:
        interface.print("The estimator had no answer at any checkpoint.")
    else:
        interface.print(f"Last estimate: r̂ = {last[0]:.3f} ± {last[1]:.3f}.")

    path: Path = (
        options.csv
        if options.csv is not None
        else Path(f"{options.user}_{options.lexicon}.csv")
    )
    write_replay_csv(path, records, checkpoints, estimates, selection)
    interface.print(f"Trajectory written to `{path}`.")
    interface.print(
        f"Visualize with `python -m emmio.lexicon.visualize replay {path}`."
    )


if __name__ == "__main__":
    main()
