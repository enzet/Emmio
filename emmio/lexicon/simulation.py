"""Simulation of the four lexicon checking methods on a fake language.

Build a synthetic Zipfian frequency list for a fake language, draw a
random knowledge profile (a 0/1 label per word) calibrated so that the
frequency-weighted share of unknown words matches a chosen rate ``r``,
then drive every checking method — FWR (``frequency``), SFWR
(``stratified``), OT (``threshold``) and LA (``logistic``) — through the
production selection (`select_next_word`) and estimation
(`estimate_rate_*`) code, and report how fast each converges to ``r``.

Run as::

    python -m emmio.lexicon.simulation --rate 3 --trials 5

Every method within a trial is checked against the same drawn lexicon,
and errors are measured against the realized rate of that lexicon (which
differs slightly from the target because labels are random).
"""

import argparse
import csv
import logging
import math
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from scipy.special import expit  # pylint: disable=no-name-in-module
from tqdm import tqdm

from emmio.lexicon.core import (
    LexiconResponse,
    TestedWord,
    UntestedWord,
    WordSelector,
    WordStates,
    create_selector,
    estimate_rate_frequency,
    estimate_rate_logistic,
    estimate_rate_stratified,
    estimate_rate_threshold,
)
from emmio.lists.config import FrequencyListConfig, FrequencyListFileFormat
from emmio.lists.frequency_list import FrequencyList
from emmio.ui import InlineElement, Interface, Table, TerminalInterface

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

logger: logging.Logger = logging.getLogger(__name__)

METHODS: tuple[str, ...] = ("frequency", "stratified", "threshold", "logistic")
"""The four checking methods, named by their selection strategy."""

KNOWLEDGE_MODELS: tuple[str, ...] = ("uniform", "logistic", "step")
"""Supported shapes of the fake learner's knowledge over frequency rank."""

METHOD_COLORS: dict[str, str] = {
    "frequency": "#2a78d6",
    "stratified": "#1baf7a",
    "threshold": "#eda100",
    "logistic": "#008300",
}
"""Categorical color per method.

The color follows the method, so plotting a subset of methods never
repaints the survivors; the hues and their order are CVD-validated.
"""

SURFACE_COLOR: str = "#fcfcfb"
INK_COLOR: str = "#0b0b0b"
SECONDARY_INK_COLOR: str = "#52514e"
MUTED_COLOR: str = "#898781"
GRID_COLOR: str = "#e1e0d9"
BASELINE_COLOR: str = "#c3c2b7"


def make_frequency_list(
    size: int, exponent: float = 1.0, scale: int = 1_000_000
) -> FrequencyList:
    """Build a Zipfian frequency list of a fake language.

    Word of rank ``i`` is named ``w{i}`` and occurs ``scale / i^exponent``
    times (at least once), so the list is already sorted by frequency.

    :param size: number of distinct words in the fake language
    :param exponent: Zipf exponent (1.0 is the classic law)
    :param scale: occurrences of the most frequent word
    :return: in-memory frequency list, not backed by any file
    """
    data: dict[str, int] = {
        f"w{rank}": max(1, round(scale / rank**exponent))
        for rank in range(1, size + 1)
    }
    return FrequencyList(
        file_path=Path("simulated"),
        config=FrequencyListConfig(
            file_format=FrequencyListFileFormat.LIST,
            language="zz",
            path="simulated",
            is_stripped=False,
        ),
        data=data,
    )


def generate_knowledge(
    frequency_list: FrequencyList,
    rate_target: float,
    model: str,
    rng: random.Random,
    steepness: float = 2.0,
) -> dict[str, int]:
    """Draw a knowledge profile with the given target rate.

    Labels are 1 for unknown and 0 for known, and are calibrated so that
    the *expected* frequency-weighted unknown share equals
    ``θ = 2^-rate_target``; the realized share of a particular draw
    differs randomly, so measure errors against `true_rate`.

    Models:

    - ``uniform``: every word is unknown with probability θ, regardless
      of rank (no rank structure at all — adversarial for the
      model-based methods);
    - ``logistic``: word of rank ``i`` is unknown with probability
      σ(steepness · (log i − μ)), with μ calibrated to hit θ (the shape
      the LA method assumes);
    - ``step``: words are known up to a boundary rank and unknown after
      it, with the boundary chosen to make the tail mass closest to θ
      (the shape the OT method assumes; deterministic).

    :param frequency_list: the fake language
    :param rate_target: target rate r, so θ = 2^-r
    :param model: one of `KNOWLEDGE_MODELS`
    :param rng: source of randomness for the Bernoulli draws
    :param steepness: slope of the logistic model in log-rank space
    :return: mapping from word to label, 1 = unknown
    """
    words: list[str] = frequency_list.get_words()
    total: int = frequency_list.get_all_occurrences()
    masses: np.ndarray = np.array(
        [frequency_list.get_occurrences(word) / total for word in words]
    )
    theta: float = 2.0**-rate_target

    match model:
        case "uniform":
            return {word: int(rng.random() < theta) for word in words}
        case "logistic":
            log_ranks: np.ndarray = np.log(
                np.arange(1, len(words) + 1, dtype=float)
            )
            # Expected unknown mass decreases in μ; bisect μ to hit θ.
            low: float = float(log_ranks[0]) - 50.0
            high: float = float(log_ranks[-1]) + 50.0
            mu: float = (low + high) / 2.0
            for _ in range(100):
                mu = (low + high) / 2.0
                mass: float = float(
                    np.dot(masses, expit(steepness * (log_ranks - mu)))
                )
                if mass > theta:
                    low = mu
                else:
                    high = mu
            probabilities: np.ndarray = expit(steepness * (log_ranks - mu))
            return {
                word: int(rng.random() < probabilities[index])
                for index, word in enumerate(words)
            }
        case "step":
            # Boundary b: ranks above b are unknown; pick b making the
            # tail mass closest to θ.
            best_boundary: int = len(words)
            best_difference: float = theta  # Tail mass 0 at b = size.
            tail: float = 0.0
            for rank in range(len(words), 0, -1):
                tail += float(masses[rank - 1])
                difference: float = abs(tail - theta)
                if difference < best_difference:
                    best_difference = difference
                    best_boundary = rank - 1
            return {
                word: int(rank > best_boundary)
                for rank, word in enumerate(words, start=1)
            }
        case _:
            message: str = f"Unknown knowledge model `{model}`."
            raise ValueError(message)


def true_rate(
    frequency_list: FrequencyList, knowledge: dict[str, int]
) -> float:
    """Compute the realized rate of a drawn knowledge profile.

    :param frequency_list: the fake language
    :param knowledge: word labels, 1 = unknown
    :return: r = -log₂ of the frequency-weighted unknown share
    """
    total: int = frequency_list.get_all_occurrences()
    theta: float = sum(
        frequency_list.get_occurrences(word) / total
        for word, label in knowledge.items()
        if label == 1
    )
    return -math.log2(theta)


def _tested_and_untested(
    frequency_list: FrequencyList, states: WordStates
) -> tuple[list[TestedWord], list[UntestedWord]]:
    """Split the fake language into tested and untested words.

    :param frequency_list: the fake language
    :param states: words answered so far
    :return: (tested words with labels, untested words), both with
        1-based ranks and frequency shares
    """
    know: str = LexiconResponse.KNOW.to_code()
    total: int = frequency_list.get_all_occurrences()
    tested: list[TestedWord] = []
    untested: list[UntestedWord] = []
    for rank, word in enumerate(frequency_list.get_words(), start=1):
        p_i: float = frequency_list.get_occurrences(word) / total
        state: tuple[str | None, bool | None] | None = states.get(word)
        if state is None:
            untested.append((rank, p_i))
        else:
            tested.append((rank, p_i, 0 if state[0] == know else 1))
    return tested, untested


@dataclass
class MethodTrajectory:
    """Estimates of one method over one trial, taken at checkpoints."""

    method: str
    """Selection strategy the trajectory was collected under."""

    checkpoints: list[int]
    """Numbers of queries at which the rate was estimated."""

    estimates: list[tuple[float, float] | None]
    """Per-checkpoint (r̂, SD), or None if the estimator had no answer."""


def run_method(
    method: str,
    frequency_list: FrequencyList,
    knowledge: dict[str, int],
    max_queries: int,
    step: int,
    n_bootstrap: int,
    precision: int,
) -> MethodTrajectory:
    """Drive one checking method over a fake learner.

    Words are selected by the production selector (the same working
    memory a checking session holds) and answered from the knowledge
    profile; at every checkpoint the estimator matching the method is
    run on the log collected so far. The ``frequency`` method samples
    with replacement (as FWR prescribes) and feeds the chronological
    sequence to its estimator; the model-based methods never repeat a
    word since answered words leave the candidate pool.

    :param method: one of `METHODS`
    :param frequency_list: the fake language
    :param knowledge: word labels, 1 = unknown
    :param max_queries: total queries to simulate
    :param step: checkpoint spacing in queries
    :param n_bootstrap: bootstrap resamples for the model-based SDs
    :param precision: full-window unknown count for the FWR estimator
    :return: the estimate trajectory
    """
    know: str = LexiconResponse.KNOW.to_code()
    dont: str = LexiconResponse.DONT.to_code()
    states: WordStates = {}
    sequence: list[int] = []
    checkpoints: list[int] = []
    estimates: list[tuple[float, float] | None] = []
    selector: WordSelector = create_selector(frequency_list, method)

    for query in tqdm(range(1, max_queries + 1), desc=method):
        word: str | None = selector.next_word()
        if word is None:
            break
        label: int = knowledge[word]
        code: str = dont if label == 1 else know
        sequence.append(0 if label == 1 else 1)
        states[word] = (code, None)
        selector.record(word, code)

        if query % step != 0 and query != max_queries:
            continue
        checkpoints.append(query)
        if method == "frequency":
            estimates.append(estimate_rate_frequency(sequence, precision))
            continue
        tested, untested = _tested_and_untested(frequency_list, states)
        match method:
            case "stratified":
                estimates.append(estimate_rate_stratified(tested, untested))
            case "threshold":
                estimates.append(
                    estimate_rate_threshold(tested, untested, n_bootstrap)
                )
            case "logistic":
                estimates.append(
                    estimate_rate_logistic(tested, untested, n_bootstrap)
                )

    return MethodTrajectory(method, checkpoints, estimates)


@dataclass
class CheckpointStats:
    """Aggregate of one method's estimates at one checkpoint."""

    mean: float | None
    """Mean r̂ over the trials where the estimator had an answer."""

    rmse: float | None
    """Root-mean-square error against the trials' realized rates."""

    count: int
    """Number of trials where the estimator had an answer."""


def _aggregate(
    methods: list[str],
    trajectories: dict[str, list[MethodTrajectory]],
    true_rates: list[float],
) -> dict[str, list[CheckpointStats]]:
    """Aggregate per-trial estimates by method and checkpoint.

    Mean and RMSE are over the trials where the estimator had an answer;
    `CheckpointStats.count` tells how many that was. Errors are measured
    against each trial's realized rate.
    """
    result: dict[str, list[CheckpointStats]] = {}
    for method in methods:
        stats: list[CheckpointStats] = []
        for index in range(len(trajectories[method][0].checkpoints)):
            values: list[tuple[float, float]] = []
            for trial, trajectory in enumerate(trajectories[method]):
                estimate: tuple[float, float] | None = trajectory.estimates[
                    index
                ]
                if estimate is not None:
                    values.append((estimate[0], true_rates[trial]))
            if not values:
                stats.append(CheckpointStats(None, None, 0))
                continue
            mean: float = sum(r_hat for r_hat, _ in values) / len(values)
            rmse: float = math.sqrt(
                sum((r_hat - r_true) ** 2 for r_hat, r_true in values)
                / len(values)
            )
            stats.append(CheckpointStats(mean, rmse, len(values)))
        result[method] = stats
    return result


def _print_report(
    interface: Interface,
    methods: list[str],
    trajectories: dict[str, list[MethodTrajectory]],
    true_rates: list[float],
    tolerance: float,
) -> None:
    """Print the convergence table and per-method summary.

    Cells are ``mean r̂/RMSE`` over the trials where the estimator had an
    answer; ``*`` marks checkpoints where some trials had none, ``—``
    where none had. Errors are against each trial's realized rate.
    """
    checkpoints: list[int] = trajectories[methods[0]][0].checkpoints
    n_trials: int = len(true_rates)
    stats: dict[str, list[CheckpointStats]] = _aggregate(
        methods, trajectories, true_rates
    )

    rows: list[list[InlineElement | str]] = []
    for index, queries in enumerate(checkpoints):
        cells: list[InlineElement | str] = [str(queries)]
        for method in methods:
            stat: CheckpointStats = stats[method][index]
            if stat.count == 0:
                cells.append("—")
            else:
                cells.append(
                    f"{stat.mean:.2f}/{stat.rmse:.2f}"
                    + ("" if stat.count == n_trials else "*")
                )
        rows.append(cells)

    interface.print(Table(["queries", *methods], rows))

    interface.print(
        f"Sustained convergence to RMSE ≤ {tolerance} (all trials):"
    )
    for method in methods:
        at: int | None = None
        for index in range(len(checkpoints) - 1, -1, -1):
            stat = stats[method][index]
            if (
                stat.count < n_trials
                or stat.rmse is None
                or stat.rmse > tolerance
            ):
                break
            at = checkpoints[index]
        interface.print(
            f"  {method}: " + (f"{at} queries" if at else "not reached")
        )


def _style_axis(axis: Axes) -> None:
    """Apply the recessive chart chrome to an axis."""
    axis.set_facecolor(SURFACE_COLOR)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    for side in ("bottom", "left"):
        axis.spines[side].set_color(BASELINE_COLOR)
    axis.tick_params(colors=MUTED_COLOR, labelsize=9)
    axis.grid(axis="y", color=GRID_COLOR, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.set_xlabel("queries", color=MUTED_COLOR, fontsize=9)


def plot_trajectories(
    methods: list[str],
    trajectories: dict[str, list[MethodTrajectory]],
    true_rates: list[float],
    tolerance: float,
    path: Path,
) -> None:
    """Draw the convergence process and save it to an image file.

    Left panel: every trial's estimate trajectory (thin) and the
    per-method mean (bold), against the mean realized rate (dashed).
    Right panel: RMSE against the realized rates, drawn only at
    checkpoints where every trial has an estimate. Methods keep their
    colors and are direct-labeled at their line ends; a method whose
    estimator never had an answer appears in the legend only.
    """
    checkpoints: list[int] = trajectories[methods[0]][0].checkpoints
    n_trials: int = len(true_rates)
    stats: dict[str, list[CheckpointStats]] = _aggregate(
        methods, trajectories, true_rates
    )

    figure, (axis_rate, axis_error) = plt.subplots(
        1, 2, figsize=(11.0, 4.5), facecolor=SURFACE_COLOR
    )
    for axis in (axis_rate, axis_error):
        _style_axis(axis)
    axis_rate.set_title(
        "Rate estimate r̂ (thin: single trials, bold: mean)",
        color=INK_COLOR,
        fontsize=11,
        loc="left",
    )
    axis_error.set_title(
        "RMSE vs realized r", color=INK_COLOR, fontsize=11, loc="left"
    )

    mean_true: float = sum(true_rates) / len(true_rates)
    axis_rate.axhline(
        mean_true, color=BASELINE_COLOR, linestyle="--", linewidth=1.0
    )
    axis_rate.annotate(
        "true r",
        (checkpoints[0], mean_true),
        textcoords="offset points",
        xytext=(0, 4),
        color=MUTED_COLOR,
        fontsize=8,
    )
    axis_error.axhline(
        tolerance, color=BASELINE_COLOR, linestyle="--", linewidth=1.0
    )
    axis_error.annotate(
        "tolerance",
        (checkpoints[0], tolerance),
        textcoords="offset points",
        xytext=(0, 4),
        color=MUTED_COLOR,
        fontsize=8,
    )

    label_ends: list[tuple[str, float]] = []
    for method in methods:
        color: str = METHOD_COLORS[method]
        for trajectory in trajectories[method]:
            values: list[float] = [
                estimate[0] if estimate else math.nan
                for estimate in trajectory.estimates
            ]
            axis_rate.plot(
                checkpoints, values, color=color, linewidth=0.8, alpha=0.3
            )
        means: list[float] = [
            stat.mean if stat.mean is not None else math.nan
            for stat in stats[method]
        ]
        axis_rate.plot(checkpoints, means, color=color, linewidth=2.0)
        finite: list[float] = [
            value for value in means if not math.isnan(value)
        ]
        if finite:
            label_ends.append((method, finite[-1]))
        errors: list[float] = [
            stat.rmse
            if stat.rmse is not None and stat.count == n_trials
            else math.nan
            for stat in stats[method]
        ]
        axis_error.plot(
            checkpoints, errors, color=color, linewidth=2.0, label=method
        )

    # Direct labels at line ends, nudged apart if they would collide.
    y_low, y_high = axis_rate.get_ylim()
    gap: float = 0.05 * (y_high - y_low)
    last: float | None = None
    for method, value in sorted(label_ends, key=lambda item: item[1]):
        position: float = value if last is None else max(value, last + gap)
        last = position
        axis_rate.annotate(
            method,
            (checkpoints[-1], position),
            textcoords="offset points",
            xytext=(6, 0),
            color=SECONDARY_INK_COLOR,
            fontsize=9,
            va="center",
        )
    axis_rate.set_xlim(right=checkpoints[-1] * 1.18)

    axis_error.set_ylim(bottom=0.0)
    axis_error.legend(frameon=False, fontsize=9, labelcolor=SECONDARY_INK_COLOR)

    figure.tight_layout()
    figure.savefig(path, dpi=150, facecolor=SURFACE_COLOR)
    plt.close(figure)


def main(arguments: list[str] | None = None) -> None:
    """Run the simulation and print the convergence report."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0]
    )
    parser.add_argument(
        "--rate", type=float, default=3.0, help="target true rate r"
    )
    parser.add_argument(
        "--size", type=int, default=10_000, help="fake language size in words"
    )
    parser.add_argument(
        "--exponent", type=float, default=1.0, help="Zipf exponent"
    )
    parser.add_argument(
        "--knowledge",
        choices=KNOWLEDGE_MODELS,
        default="logistic",
        help="shape of the fake learner's knowledge over rank",
    )
    parser.add_argument(
        "--steepness",
        type=float,
        default=2.0,
        help="slope of the logistic knowledge model in log-rank space",
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=METHODS,
        default=list(METHODS),
        help="checking methods to simulate",
    )
    parser.add_argument(
        "--max-queries", type=int, default=300, help="queries per trial"
    )
    parser.add_argument(
        "--step", type=int, default=25, help="checkpoint spacing in queries"
    )
    parser.add_argument(
        "--trials", type=int, default=3, help="independent knowledge draws"
    )
    parser.add_argument(
        "--n-bootstrap",
        type=int,
        default=50,
        help="bootstrap resamples for OT/LA standard deviations",
    )
    parser.add_argument(
        "--precision",
        type=int,
        default=100,
        help="full-window unknown count for the FWR estimator",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.1,
        help="RMSE defining convergence in the summary",
    )
    parser.add_argument("--seed", type=int, default=0, help="random seed")
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="also write per-trial trajectories to this CSV file",
    )
    parser.add_argument(
        "--plot",
        type=Path,
        default=None,
        help="also render the convergence process to this image file",
    )
    options: argparse.Namespace = parser.parse_args(arguments)
    interface: Interface = TerminalInterface(use_input=False)

    frequency_list: FrequencyList = make_frequency_list(
        options.size, options.exponent
    )
    interface.print(
        f"Fake language: {options.size} words, "
        f"Zipf exponent {options.exponent}."
    )
    interface.print(
        f"Knowledge model: {options.knowledge}, "
        f"target r = {options.rate:.3f}, {options.trials} trial(s)."
    )

    trajectories: dict[str, list[MethodTrajectory]] = {
        method: [] for method in options.methods
    }
    true_rates: list[float] = []
    for trial in range(options.trials):
        rng: random.Random = random.Random(f"{options.seed}-{trial}")
        knowledge: dict[str, int] = generate_knowledge(
            frequency_list,
            options.rate,
            options.knowledge,
            rng,
            options.steepness,
        )
        r_true: float = true_rate(frequency_list, knowledge)
        true_rates.append(r_true)
        for method in options.methods:
            # The production selection code draws from the global
            # generator; reseed it so trials are reproducible.
            random.seed(f"{options.seed}-{trial}-{method}")
            trajectories[method].append(
                run_method(
                    method,
                    frequency_list,
                    knowledge,
                    options.max_queries,
                    options.step,
                    options.n_bootstrap,
                    options.precision,
                )
            )
        logger.info("Trial %d done, realized r = %.3f.", trial, r_true)

    realized: str = ", ".join(f"{value:.3f}" for value in true_rates)
    interface.print(f"Realized r per trial: {realized}.")
    _print_report(
        interface, options.methods, trajectories, true_rates, options.tolerance
    )

    if options.csv is not None:
        with options.csv.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(
                ["method", "trial", "queries", "r_hat", "sd", "r_true"]
            )
            for method in options.methods:
                for trial, trajectory in enumerate(trajectories[method]):
                    for queries, estimate in zip(
                        trajectory.checkpoints,
                        trajectory.estimates,
                        strict=True,
                    ):
                        r_hat, sd = estimate if estimate else ("", "")
                        writer.writerow(
                            [
                                method,
                                trial,
                                queries,
                                r_hat,
                                sd,
                                true_rates[trial],
                            ]
                        )
        interface.print(f"Trajectories written to `{options.csv}`.")

    if options.plot is not None:
        plot_trajectories(
            options.methods,
            trajectories,
            true_rates,
            options.tolerance,
            options.plot,
        )
        interface.print(f"Plot written to `{options.plot}`.")


if __name__ == "__main__":
    main()
