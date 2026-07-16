"""Shared Matplotlib styling for rate estimate trajectory plots.

The visualizer (`emmio.lexicon.visualize`) draws the same kind of
picture — a rate estimate trajectory over queries — from the CSV files
of both the simulation (`emmio.lexicon.simulation`) and the real-log
replay (`emmio.lexicon.replay`); the chart chrome lives here so every
plot renders in one visual style.
"""

import math

from matplotlib.axes import Axes

from emmio.lexicon.core import RateEstimator

METHOD_COLORS: dict[RateEstimator, str] = {
    RateEstimator.FREQUENCY: "#2a78d6",
    RateEstimator.STRATIFIED: "#1baf7a",
    RateEstimator.THRESHOLD: "#eda100",
    RateEstimator.LOGISTIC: "#008300",
}
"""Categorical color per checking method.

The color follows the method, so plotting a subset of methods never
repaints the survivors; the hues and their order are CVD-validated.
"""

SURFACE_COLOR: str = "#fcfcfb"
INK_COLOR: str = "#000000"
SECONDARY_INK_COLOR: str = "#000000"
MUTED_COLOR: str = "#000000"
GRID_COLOR: str = "#E0E0E0"
BASELINE_COLOR: str = "#000000"


def style_axis(axis: Axes) -> None:
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


def trajectory_values(
    estimates: list[tuple[float, float] | None], sd_factor: float = 0.0
) -> list[float]:
    """Extract plottable values from a trajectory of estimates.

    :param estimates: per-checkpoint (r̂, SD), or None where the
        estimator had no answer
    :param sd_factor: how many standard deviations to offset each value,
        e.g. ±1 for the edges of an error band
    :return: r̂ + sd_factor · SD per checkpoint, NaN marking the gaps
    """
    return [
        estimate[0] + sd_factor * estimate[1] if estimate else math.nan
        for estimate in estimates
    ]


def plot_estimates(
    axis: Axes,
    checkpoints: list[int],
    estimates: list[tuple[float, float] | None],
    color: str,
    *,
    band: bool = True,
) -> None:
    """Draw an estimate trajectory, optionally with its ±1 SD band.

    :param axis: axis to draw on
    :param checkpoints: query numbers of the checkpoints
    :param estimates: per-checkpoint (r̂, SD), or None where the
        estimator had no answer
    :param color: line and band color
    :param band: also fill the ±1 SD band around the line
    """
    if band:
        axis.fill_between(
            checkpoints,
            trajectory_values(estimates, -1.0),
            trajectory_values(estimates, 1.0),
            color=color,
            alpha=0.15,
            linewidth=0,
        )
    axis.plot(
        checkpoints, trajectory_values(estimates), color=color, linewidth=2.0
    )


def spread_label_positions(
    ends: list[tuple[str, float]], y_low: float, y_high: float
) -> list[tuple[str, float]]:
    """Nudge direct labels apart vertically on collision.

    :param ends: (label, y value at the line end) pairs
    :param y_low: bottom of the visible value range
    :param y_high: top of the visible value range
    :return: (label, y position) pairs, sorted bottom to top
    """
    gap: float = 0.05 * (y_high - y_low)
    positions: list[tuple[str, float]] = []
    last: float | None = None
    for label, value in sorted(ends, key=lambda item: item[1]):
        position: float = value if last is None else max(value, last + gap)
        last = position
        positions.append((label, position))
    return positions


def label_line_ends(
    axis: Axes, ends: list[tuple[str, float]], x: float
) -> None:
    """Direct-label lines at their right ends, nudged apart on collision.

    :param axis: axis holding the lines
    :param ends: (label, y value at the line end) pairs
    :param x: x coordinate of the line ends
    """
    y_low, y_high = axis.get_ylim()
    for label, position in spread_label_positions(ends, y_low, y_high):
        axis.annotate(
            label,
            (x, position),
            textcoords="offset points",
            xytext=(6, 0),
            color=SECONDARY_INK_COLOR,
            fontsize=9,
            va="center",
        )
