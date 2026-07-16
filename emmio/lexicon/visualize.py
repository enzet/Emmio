"""Visualize CSV trajectories written by the simulation and the replay.

Read a CSV file produced by `emmio.lexicon.simulation` or
`emmio.lexicon.replay` and draw the rate estimate trajectories in the
shared visual style, without recomputing anything.

Run as::

    python -m emmio.lexicon.visualize simulation simulation.csv
    python -m emmio.lexicon.visualize replay john_fr_1.csv

The output image file defaults to the CSV file with a ``.png`` suffix.
"""

import argparse
import csv
import math
from pathlib import Path

from matplotlib import pyplot as plt

from emmio.lexicon.config import LexiconSelection
from emmio.lexicon.core import RATE_ESTIMATOR_BY_SELECTION, LexiconResponse
from emmio.lexicon.plotting import (
    BASELINE_COLOR,
    INK_COLOR,
    METHOD_COLORS,
    MUTED_COLOR,
    SECONDARY_INK_COLOR,
    SURFACE_COLOR,
    label_line_ends,
    plot_estimates,
    style_axis,
    trajectory_values,
)
from emmio.lexicon.simulation import (
    CheckpointStats,
    MethodTrajectory,
    aggregate_trajectories,
)
from emmio.ui import Interface, TerminalInterface

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


def _parse_estimate(row: dict[str, str]) -> tuple[float, float] | None:
    """Read the (r̂, SD) pair of a CSV row, None if the cells are empty."""
    if row["r_hat"] == "":
        return None
    return float(row["r_hat"]), float(row["sd"])


def read_simulation_csv(
    path: Path,
) -> tuple[
    list[LexiconSelection],
    dict[LexiconSelection, list[MethodTrajectory]],
    list[float],
]:
    """Read per-trial trajectories written by the simulation.

    :param path: CSV file with columns ``method``, ``trial``,
        ``queries``, ``r_hat``, ``sd``, ``r_true``
    :return: (methods in file order, per-method trajectories, realized
        rate per trial)
    """
    methods: list[LexiconSelection] = []
    trajectories: dict[LexiconSelection, list[MethodTrajectory]] = {}
    true_rates: dict[int, float] = {}

    with path.open(encoding="utf-8", newline="") as input_:
        for row in csv.DictReader(input_):
            method: LexiconSelection = LexiconSelection(row["method"])
            trial: int = int(row["trial"])
            if method not in trajectories:
                methods.append(method)
                trajectories[method] = []
            if trial == len(trajectories[method]):
                trajectories[method].append(MethodTrajectory(method, [], []))
            trajectory: MethodTrajectory = trajectories[method][trial]
            trajectory.checkpoints.append(int(row["queries"]))
            trajectory.estimates.append(_parse_estimate(row))
            true_rates[trial] = float(row["r_true"])

    return (
        methods,
        trajectories,
        [true_rates[trial] for trial in sorted(true_rates)],
    )


def read_replay_csv(
    path: Path,
) -> tuple[
    list[int], list[tuple[float, float] | None], list[int], LexiconSelection
]:
    """Read a replayed trajectory written by the replay.

    :param path: CSV file with columns ``queries``, ``response``,
        ``checkpoint``, ``r_hat``, ``sd``, ``selection``
    :return: (checkpoint query numbers, per-checkpoint estimates, query
        numbers of "don't know" answers, the lexicon's selection
        strategy)
    """
    dont: str = LexiconResponse.DONT.to_code()
    checkpoints: list[int] = []
    estimates: list[tuple[float, float] | None] = []
    dont_steps: list[int] = []
    selection: LexiconSelection | None = None

    with path.open(encoding="utf-8", newline="") as input_:
        for row in csv.DictReader(input_):
            selection = LexiconSelection(row["selection"])
            number: int = int(row["queries"])
            if row["response"] == dont:
                dont_steps.append(number)
            if row["checkpoint"] == "1":
                checkpoints.append(number)
                estimates.append(_parse_estimate(row))

    if selection is None:
        message: str = f"CSV file `{path}` has no rows."
        raise SystemExit(message)
    return checkpoints, estimates, dont_steps, selection


def plot_simulation(
    methods: list[LexiconSelection],
    trajectories: dict[LexiconSelection, list[MethodTrajectory]],
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
    stats: dict[LexiconSelection, list[CheckpointStats]] = (
        aggregate_trajectories(methods, trajectories, true_rates)
    )

    figure, (axis_rate, axis_error) = plt.subplots(
        1, 2, figsize=(11.0, 4.5), facecolor=SURFACE_COLOR
    )
    for axis in (axis_rate, axis_error):
        style_axis(axis)
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
        color: str = METHOD_COLORS[RATE_ESTIMATOR_BY_SELECTION[method]]
        for trajectory in trajectories[method]:
            axis_rate.plot(
                checkpoints,
                trajectory_values(trajectory.estimates),
                color=color,
                linewidth=0.8,
                alpha=0.3,
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

    label_line_ends(axis_rate, label_ends, float(checkpoints[-1]))
    axis_rate.set_xlim(right=checkpoints[-1] * 1.18)

    axis_error.set_ylim(bottom=0.0)
    axis_error.legend(frameon=False, fontsize=9, labelcolor=SECONDARY_INK_COLOR)

    figure.tight_layout()
    figure.savefig(path, dpi=150, facecolor=SURFACE_COLOR)
    plt.close(figure)


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
    """Visualize a trajectory CSV file."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0]
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    simulation_parser = subparsers.add_parser(
        "simulation", help="visualize a CSV file written by the simulation"
    )
    simulation_parser.add_argument(
        "csv", type=Path, help="CSV file written by `emmio.lexicon.simulation`"
    )
    simulation_parser.add_argument(
        "--plot",
        type=Path,
        default=None,
        help="output image file (default: the CSV file with `.png` suffix)",
    )
    simulation_parser.add_argument(
        "--tolerance",
        type=float,
        default=0.1,
        help="RMSE drawn as the tolerance baseline",
    )

    replay_parser = subparsers.add_parser(
        "replay", help="visualize a CSV file written by the replay"
    )
    replay_parser.add_argument(
        "csv", type=Path, help="CSV file written by `emmio.lexicon.replay`"
    )
    replay_parser.add_argument(
        "--plot",
        type=Path,
        default=None,
        help="output image file (default: the CSV file with `.png` suffix)",
    )
    replay_parser.add_argument(
        "--title",
        default=None,
        help="chart title (default: built from the CSV file name)",
    )

    options: argparse.Namespace = parser.parse_args(arguments)
    interface: Interface = TerminalInterface(use_input=False)
    path: Path = (
        options.plot
        if options.plot is not None
        else options.csv.with_suffix(".png")
    )

    match options.command:
        case "simulation":
            methods, trajectories, true_rates = read_simulation_csv(options.csv)
            plot_simulation(
                methods, trajectories, true_rates, options.tolerance, path
            )
        case "replay":
            checkpoints, estimates, dont_steps, selection = read_replay_csv(
                options.csv
            )
            title: str = (
                options.title
                if options.title is not None
                else f"Rate estimate r̂ ± SD — `{options.csv.stem}` "
                f"({selection})"
            )
            plot_replay(
                checkpoints, estimates, dont_steps, selection, title, path
            )

    interface.print(f"Plot written to `{path}`.")


if __name__ == "__main__":
    main()
