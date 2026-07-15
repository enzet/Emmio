"""Shared Matplotlib styling for rate estimate trajectory plots.

The simulation (`emmio.lexicon.simulation`) and the real-log replay
(`emmio.lexicon.replay`) draw the same kind of picture — a rate estimate
trajectory over queries — and share their chart chrome here so both
render in one visual style.
"""

import math

from matplotlib.axes import Axes

METHOD_COLORS: dict[str, str] = {
    "frequency": "#2a78d6",
    "stratified": "#1baf7a",
    "threshold": "#eda100",
    "logistic": "#008300",
}
"""Categorical color per checking method.

The color follows the method, so plotting a subset of methods never
repaints the survivors; the hues and their order are CVD-validated.
"""

SURFACE_COLOR: str = "#fcfcfb"
INK_COLOR: str = "#0b0b0b"
SECONDARY_INK_COLOR: str = "#52514e"
MUTED_COLOR: str = "#898781"
GRID_COLOR: str = "#e1e0d9"
BASELINE_COLOR: str = "#c3c2b7"


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


def label_line_ends(
    axis: Axes, ends: list[tuple[str, float]], x: float
) -> None:
    """Direct-label lines at their right ends, nudged apart on collision.

    :param axis: axis holding the lines
    :param ends: (label, y value at the line end) pairs
    :param x: x coordinate of the line ends
    """
    y_low, y_high = axis.get_ylim()
    gap: float = 0.05 * (y_high - y_low)
    last: float | None = None
    for label, value in sorted(ends, key=lambda item: item[1]):
        position: float = value if last is None else max(value, last + gap)
        last = position
        axis.annotate(
            label,
            (x, position),
            textcoords="offset points",
            xytext=(6, 0),
            color=SECONDARY_INK_COLOR,
            fontsize=9,
            va="center",
        )
