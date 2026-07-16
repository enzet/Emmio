"""Replay the checking process of a real lexicon, simulation-style.

Fetch the chronological answer log of one user's lexicon from the
database, re-run the production rate estimator after every answer (the
same `estimate_rate_with_sd` path the API uses), and draw the estimate
trajectory r̂ with its ±1 SD band, styled like the simulation plots.

Run as::

    python -m emmio.lexicon.replay --user john --lexicon fr_1

The frequency list configured for the lexicon is loaded from the Emmio
data directory (`EMMIO_DATA_DIR`, default `~/.emmio`); the log comes
from PostgreSQL.
"""

import argparse
import os
from pathlib import Path

from matplotlib import pyplot as plt
from tqdm import tqdm

from emmio.data import Data
from emmio.lexicon.config import LexiconSelection
from emmio.lexicon.core import (
    RATE_ESTIMATOR_BY_SELECTION,
    LexiconResponse,
    WordStates,
    estimate_rate_with_sd,
)
from emmio.lexicon.plotting import (
    INK_COLOR,
    METHOD_COLORS,
    MUTED_COLOR,
    SURFACE_COLOR,
    label_line_ends,
    plot_estimates,
    style_axis,
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
) -> tuple[list[int], list[tuple[float, float] | None], list[int]]:
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
    :return: (checkpoint query numbers, per-checkpoint estimates, query
        numbers of "don't know" answers)
    """
    know: str = LexiconResponse.KNOW.to_code()
    dont: str = LexiconResponse.DONT.to_code()
    states: WordStates = {}
    sequence: list[int] = []
    checkpoints: list[int] = []
    estimates: list[tuple[float, float] | None] = []
    dont_steps: list[int] = []

    for number, (word, code) in tqdm(enumerate(records, start=1)):
        states[word] = (code, None)
        if code == know:
            sequence.append(1)
        elif code == dont:
            sequence.append(0)
            dont_steps.append(number)
        if number % step != 0 and number != len(records):
            continue
        checkpoints.append(number)
        estimates.append(
            estimate_rate_with_sd(
                selection, frequency_list, states, sequence, precision
            )
        )

    return checkpoints, estimates, dont_steps


def plot_replay(
    checkpoints: list[int],
    estimates: list[tuple[float, float] | None],
    dont_steps: list[int],
    selection: LexiconSelection,
    title: str,
    path: Path,
) -> None:
    """Draw the replayed estimate trajectory and save it to an image file.

    The r̂ line with its ±1 SD band in the method's color, ticks along
    the bottom marking the "don't know" answers, and the last estimate
    direct-labeled at the line end.

    :param checkpoints: query numbers of the checkpoints
    :param estimates: per-checkpoint (r̂, SD), or None where the
        estimator had no answer
    :param dont_steps: query numbers of "don't know" answers
    :param selection: the lexicon's selection strategy, for the color
    :param title: chart title
    :param path: output image file
    """
    figure, axis = plt.subplots(figsize=(9.0, 4.5), facecolor=SURFACE_COLOR)
    style_axis(axis)
    axis.set_title(title, color=INK_COLOR, fontsize=11, loc="left")

    color: str = METHOD_COLORS[RATE_ESTIMATOR_BY_SELECTION[selection]]
    plot_estimates(axis, checkpoints, estimates, color)

    # Ticks along the bottom mark the "don't know" answers.
    y_low, y_high = axis.get_ylim()
    tick_height: float = 0.04 * (y_high - y_low)
    if dont_steps:
        axis.vlines(
            dont_steps,
            y_low,
            y_low + tick_height,
            color=MUTED_COLOR,
            linewidth=1.0,
        )
        axis.annotate(
            "don't know answers",
            (checkpoints[-1], y_low + tick_height / 2.0),
            textcoords="offset points",
            xytext=(6, 0),
            color=MUTED_COLOR,
            fontsize=8,
            va="center",
        )
    axis.set_ylim(y_low, y_high)
    axis.set_xlim(0, checkpoints[-1] * 1.18)

    last: tuple[float, float] | None = next(
        (estimate for estimate in reversed(estimates) if estimate is not None),
        None,
    )
    if last is not None:
        r_hat, sd = last
        label_line_ends(
            axis,
            [(f"r̂ = {r_hat:.2f} ± {sd:.2f}", r_hat)],
            float(checkpoints[-1]),
        )

    figure.tight_layout()
    figure.savefig(path, dpi=150, facecolor=SURFACE_COLOR)
    plt.close(figure)


def main(arguments: list[str] | None = None) -> None:
    """Replay a lexicon's checking process and plot the estimates."""
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
        "--plot",
        type=Path,
        default=None,
        help="output image file (default `<user>_<lexicon>.png`)",
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

    checkpoints, estimates, dont_steps = replay(
        records, selection, frequency_list, options.step, options.precision
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
        options.plot
        if options.plot is not None
        else Path(f"{options.user}_{options.lexicon}.png")
    )
    plot_replay(
        checkpoints,
        estimates,
        dont_steps,
        selection,
        f"Rate estimate r̂ ± SD — user `{options.user}`, "
        f"lexicon `{options.lexicon}` ({selection})",
        path,
    )
    interface.print(f"Plot written to `{path}`.")


if __name__ == "__main__":
    main()
