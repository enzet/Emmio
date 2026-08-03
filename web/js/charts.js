import { languageName } from "./format.js";

// Convergence chart of the rate estimate (check page): an inline SVG seeded
// from `/rate-trajectory` and grown live from per-answer `/rate-estimate`
// values. Colors come from CSS variables in `base.css` (theme-aware); the
// series color follows the estimator (`data-method` on the figure).
export function createTrajectoryChart(figure, svg, tooltip) {
    const SVG_NS = "http://www.w3.org/2000/svg";
    const MARGIN = { top: 10, right: 110, bottom: 20, left: 40 };

    let seed = null; // { method, total, checkpoints } from the API.
    let checkedAtSeed = 0; // Session answers already included in the seed.
    const live = new Map(); // Answer number -> { rate, sd }, this session.
    let points = []; // Merged { q, rate, sd } to plot, oldest first.
    let scale = null; // Last render's scales, for the hover layer.

    // The hover layer is created once and re-appended after every rebuild
    // (setting `innerHTML` wipes the SVG).
    const crosshair = document.createElementNS(SVG_NS, "line");
    crosshair.setAttribute("class", "crosshair");
    const focusDot = document.createElementNS(SVG_NS, "circle");
    focusDot.setAttribute("class", "focus-dot");
    focusDot.setAttribute("r", "4");

    function hideHover() {
        crosshair.style.visibility = "hidden";
        focusDot.style.visibility = "hidden";
        tooltip.hidden = true;
    }

    // The x position of this session's `checked`-th answer: the seed may
    // already contain answers given before it finished loading.
    function answerNumber(checked) {
        return seed.total + checked - checkedAtSeed;
    }

    function merge() {
        points = seed.checkpoints.map((point) => ({
            q: point.queries,
            rate: point.rate,
            sd: point.sd,
        }));
        for (const [q, estimate] of [...live.entries()].sort(
            (a, b) => a[0] - b[0],
        )) {
            points.push({ q, rate: estimate.rate, sd: estimate.sd });
        }
    }

    // The gridline/tick spacing covering `span` with about `count` steps,
    // snapped to a clean 1/2/5 × 10^k value.
    function niceStep(span, count) {
        const raw = span / count;
        const power = 10 ** Math.floor(Math.log10(raw));
        for (const multiple of [1, 2, 5]) {
            if (raw <= multiple * power) return multiple * power;
        }
        return 10 * power;
    }

    function tickLabel(value) {
        return Number.isInteger(value)
            ? value.toLocaleString("en-US")
            : String(Number(value.toFixed(2)));
    }

    function render() {
        if (!seed) return;
        const known = points.filter((point) => point.rate !== null);
        if (known.length < 2) {
            figure.hidden = true;
            return;
        }
        figure.hidden = false;
        const width = svg.clientWidth;
        const height = svg.clientHeight;
        if (!width || !height) return;
        svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

        const maxQ = points[points.length - 1].q;
        let yMin = Infinity;
        let yMax = -Infinity;
        for (const point of known) {
            yMin = Math.min(yMin, point.rate - (point.sd || 0));
            yMax = Math.max(yMax, point.rate + (point.sd || 0));
        }
        if (yMin === yMax) {
            yMin -= 0.5;
            yMax += 0.5;
        }
        const pad = (yMax - yMin) * 0.08;
        yMin -= pad;
        yMax += pad;

        const plot = {
            left: MARGIN.left,
            right: width - MARGIN.right,
            top: MARGIN.top,
            bottom: height - MARGIN.bottom,
        };
        const x = (q) =>
            plot.left + (q / maxQ) * (plot.right - plot.left);
        const y = (value) =>
            plot.bottom -
            ((value - yMin) / (yMax - yMin)) * (plot.bottom - plot.top);
        scale = { x, y, plot };

        const parts = [];

        // Horizontal hairline gridlines with their rate labels.
        const yStep = niceStep(yMax - yMin, 3);
        for (
            let index = Math.ceil(yMin / yStep);
            index * yStep <= yMax + yStep * 1e-6;
            index += 1
        ) {
            const value = index * yStep;
            const line = y(value);
            parts.push(
                `<line class="grid" x1="${plot.left}" y1="${line}"` +
                    ` x2="${plot.right}" y2="${line}"/>`,
                `<text class="tick-label" x="${plot.left - 6}" y="${line}"` +
                    ` text-anchor="end" dominant-baseline="middle">` +
                    `${tickLabel(value)}</text>`,
            );
        }

        // The baseline and a few answer-count ticks along it.
        parts.push(
            `<line class="grid" x1="${plot.left}" y1="${plot.bottom}"` +
                ` x2="${plot.right}" y2="${plot.bottom}"/>`,
        );
        const xStep = Math.max(1, niceStep(maxQ, 4));
        for (let value = 0; value <= maxQ; value += xStep) {
            parts.push(
                `<text class="tick-label" x="${x(value)}"` +
                    ` y="${height - 4}" text-anchor="middle">` +
                    `${tickLabel(value)}</text>`,
            );
        }

        // The r line with its ± SD band, split where the estimator had no
        // answer.
        const runs = [];
        let run = [];
        for (const point of points) {
            if (point.rate === null) {
                if (run.length) runs.push(run);
                run = [];
            } else {
                run.push(point);
            }
        }
        if (run.length) runs.push(run);
        for (const segment of runs) {
            if (segment.length < 2) continue;
            const upper = segment
                .map((p) => `${x(p.q)},${y(p.rate + (p.sd || 0))}`)
                .join(" L ");
            const lower = segment
                .slice()
                .reverse()
                .map((p) => `${x(p.q)},${y(p.rate - (p.sd || 0))}`)
                .join(" L ");
            parts.push(`<path class="band" d="M ${upper} L ${lower} Z"/>`);
            const line = segment
                .map((p) => `${x(p.q)},${y(p.rate)}`)
                .join(" L ");
            parts.push(`<path class="line" d="M ${line}"/>`);
        }

        // The last estimate, direct-labeled at the line end.
        const last = known[known.length - 1];
        const labelY = Math.min(
            Math.max(y(last.rate), plot.top + 8),
            plot.bottom - 4,
        );
        parts.push(
            `<text class="end-label" x="${x(last.q) + 8}" y="${labelY}"` +
                ` dominant-baseline="middle">r = ${last.rate.toFixed(2)}` +
                ` ± ${(last.sd || 0).toFixed(2)}</text>`,
        );

        svg.innerHTML = parts.join("");
        svg.append(crosshair, focusDot);
        hideHover();
    }

    // Crosshair and tooltip: the whole SVG is the hit target, the reader
    // aims at an x position and the nearest estimate answers.
    svg.addEventListener("pointermove", (event) => {
        if (!scale) return;
        const known = points.filter((point) => point.rate !== null);
        if (!known.length) return;
        const px = event.clientX - svg.getBoundingClientRect().left;
        let nearest = known[0];
        for (const point of known) {
            if (Math.abs(scale.x(point.q) - px) <
                Math.abs(scale.x(nearest.q) - px)) {
                nearest = point;
            }
        }
        const cx = scale.x(nearest.q);
        const cy = scale.y(nearest.rate);
        crosshair.setAttribute("x1", cx);
        crosshair.setAttribute("x2", cx);
        crosshair.setAttribute("y1", scale.plot.top);
        crosshair.setAttribute("y2", scale.plot.bottom);
        crosshair.style.visibility = "visible";
        focusDot.setAttribute("cx", cx);
        focusDot.setAttribute("cy", cy);
        focusDot.style.visibility = "visible";
        tooltip.textContent =
            `r = ${nearest.rate.toFixed(2)} ± ${(nearest.sd || 0).toFixed(2)}` +
            ` · ${nearest.q.toLocaleString("en-US")} answers`;
        tooltip.hidden = false;
        tooltip.style.left = `${Math.max(
            0,
            Math.min(cx + 10, figure.clientWidth - tooltip.offsetWidth - 4),
        )}px`;
        tooltip.style.top = `${Math.max(0, cy - tooltip.offsetHeight - 8)}px`;
    });
    svg.addEventListener("pointerleave", hideHover);
    window.addEventListener("resize", render);

    return {
        // Seed the chart with the replayed history. `checkedNow` is how many
        // answers this session had already recorded when the seed was
        // requested, so live points continue where the seed ends.
        setSeed(data, checkedNow) {
            seed = data;
            checkedAtSeed = checkedNow;
            figure.dataset.method = data.method;
            merge();
            render();
        },
        // A fresh estimate for the state after `checked` session answers.
        // Points beyond it are stale (an undo happened since they were
        // plotted).
        noteEstimate(checked, rate, sd) {
            if (!seed) return;
            const q = answerNumber(checked);
            for (const key of [...live.keys()]) {
                if (key > q) live.delete(key);
            }
            if (checked > checkedAtSeed && rate !== null) {
                live.set(q, { rate, sd });
            }
            merge();
            render();
        },
        // An undo: drop the live points past the rewound position.
        noteUndo(checked) {
            if (!seed) return;
            const q = answerNumber(checked);
            for (const key of [...live.keys()]) {
                if (key > q) live.delete(key);
            }
            merge();
            render();
        },
    };
}

// Dashboard vocabulary-level history: one r line per language over calendar
// time, drawn like `createTrajectoryChart` but from a fetched snapshot
// (`setData`, reloaded whenever the month/year interval toggle changes)
// rather than a growing live session. Every line is plain (no
// legend/per-language color) — hovering a language's dashboard row or a
// line here highlights the other via `onHoverLanguage`/`highlight()`. No SD
// bands: they'd be indistinguishable across languages sharing one plain
// color.
//
// `onHoverLanguage`, if given, is called with a language code when the
// pointer settles nearest that line, and `null` when it leaves.
export function createLanguageHistoryChart(figure, svg, tooltip, onHoverLanguage) {
    const SVG_NS = "http://www.w3.org/2000/svg";
    // Left/right are a thin safety margin, not real padding: axis labels sit
    // inside the plot (no legend needed — that's what the hover sync above
    // is for).
    const MARGIN = { top: 10, right: 4, bottom: 20, left: 4 };

    let series = []; // [{ language, points: [{ date, rate, sd }] }].
    let interval = "month"; // Grid spacing of `series`' points, from `setData`.
    let scale = null; // Last render's scales, for the hover layer.
    let activeLanguage = null; // Set by `highlight()`; survives a re-render.

    // Dim every line except `language`'s, which instead turns blue (or, for
    // `null`, undo both).
    function applyHighlight(language) {
        for (const path of svg.querySelectorAll(".line")) {
            const isActive =
                language !== null && path.dataset.language === language;
            path.classList.toggle("active", isActive);
            path.classList.toggle("dimmed", language !== null && !isActive);
        }
    }

    // The hover layer is created once and re-appended after every rebuild
    // (setting `innerHTML` wipes the SVG).
    const crosshair = document.createElementNS(SVG_NS, "line");
    crosshair.setAttribute("class", "crosshair");
    const focusDot = document.createElementNS(SVG_NS, "circle");
    focusDot.setAttribute("class", "focus-dot");
    focusDot.setAttribute("r", "4");

    function hideHover() {
        crosshair.style.visibility = "hidden";
        focusDot.style.visibility = "hidden";
        tooltip.hidden = true;
        if (onHoverLanguage) onHoverLanguage(null);
    }

    function tickLabel(value) {
        return Number.isInteger(value)
            ? value.toLocaleString("en-US")
            : String(Number(value.toFixed(2)));
    }

    // `_grid_points` assigns every resampled point's date at UTC midnight
    // (the backend's calendar, not the viewer's), so every date computed or
    // displayed here uses UTC fields/`timeZone: "UTC"` too — mixing in the
    // viewer's local timezone would drift the grid by the UTC offset, which
    // in the worst case (an offset large enough to cross a day boundary)
    // makes `monthStarts`/`yearStarts` miss a tick entirely.
    function dateLabel(date) {
        return interval === "year"
            ? String(date.getUTCFullYear())
            : date.toLocaleDateString(undefined, {
                  timeZone: "UTC",
                  month: "short",
                  day: "numeric",
              });
    }

    // The first of each month from `minDate` to `maxDate`, as timestamps.
    function monthStarts(minDate, maxDate) {
        const first = new Date(minDate);
        let cursor = Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), 1);
        if (cursor < minDate) {
            cursor = Date.UTC(
                first.getUTCFullYear(),
                first.getUTCMonth() + 1,
                1,
            );
        }
        const ticks = [];
        while (cursor <= maxDate) {
            ticks.push(cursor);
            const date = new Date(cursor);
            cursor = Date.UTC(
                date.getUTCFullYear(),
                date.getUTCMonth() + 1,
                1,
            );
        }
        return ticks;
    }

    // The first of each year from `minDate` to `maxDate`, as timestamps —
    // `monthStarts`' counterpart for `interval === "year"`.
    function yearStarts(minDate, maxDate) {
        const first = new Date(minDate);
        let cursor = Date.UTC(first.getUTCFullYear(), 0, 1);
        if (cursor < minDate) {
            cursor = Date.UTC(first.getUTCFullYear() + 1, 0, 1);
        }
        const ticks = [];
        while (cursor <= maxDate) {
            ticks.push(cursor);
            cursor = Date.UTC(new Date(cursor).getUTCFullYear() + 1, 0, 1);
        }
        return ticks;
    }

    function render() {
        const known = series.filter((one) => one.points.length >= 2);
        if (known.length === 0) {
            figure.hidden = true;
            return;
        }
        figure.hidden = false;
        const width = svg.clientWidth;
        const height = svg.clientHeight;
        if (!width || !height) return;
        svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

        let minDate = Infinity;
        let maxDate = -Infinity;
        let yMin = Infinity;
        let yMax = -Infinity;
        for (const one of known) {
            for (const point of one.points) {
                const t = point.date.getTime();
                minDate = Math.min(minDate, t);
                maxDate = Math.max(maxDate, t);
                yMin = Math.min(yMin, point.rate - (point.sd || 0));
                yMax = Math.max(yMax, point.rate + (point.sd || 0));
            }
        }
        if (minDate === maxDate) maxDate = minDate + 1;
        // The axis floor is never negative (a rate can't be), and the
        // ceiling is always a whole number, so every integer between the two
        // gets its own gridline below — no fractional padding.
        yMin = Math.max(0, Math.floor(yMin));
        yMax = Math.max(yMin + 1, Math.ceil(yMax));

        const plot = {
            left: MARGIN.left,
            right: width - MARGIN.right,
            top: MARGIN.top,
            bottom: height - MARGIN.bottom,
        };
        const x = (t) =>
            plot.left +
            ((t - minDate) / (maxDate - minDate)) * (plot.right - plot.left);
        const y = (value) =>
            plot.bottom -
            ((value - yMin) / (yMax - yMin)) * (plot.bottom - plot.top);
        scale = { x, y, plot, known };

        const parts = [];

        // Hairline gridlines with rate labels; with no left margin, labels
        // sit just below their own gridline instead. "0" is skipped — it'd
        // coincide with the baseline drawn below.
        for (let value = yMin; value <= yMax; value += 1) {
            if (value === 0) continue;
            const line = y(value);
            parts.push(
                `<line class="grid" x1="${plot.left}" y1="${line}"` +
                    ` x2="${plot.right}" y2="${line}"/>`,
                `<text class="tick-label" x="${plot.left + 0}"` +
                    ` y="${line + 16}" text-anchor="start">` +
                    `${tickLabel(value)}</text>`,
            );
        }

        // A tick label at `t`, anchored to stay inside the plot even at the
        // very first/last tick (where centering on `x(t)` would run past the
        // edge, now that there's no left/right margin to absorb that).
        function dateTickLabel(t, index, count, text) {
            const anchor =
                index === 0 ? "start" : index === count - 1 ? "end" : "middle";
            const labelX =
                anchor === "start"
                    ? plot.left
                    : anchor === "end"
                      ? plot.right
                      : x(t);
            return (
                `<text class="tick-label" x="${labelX}" y="${height - 4}"` +
                ` text-anchor="${anchor}">${text}</text>`
            );
        }

        // The baseline and date ticks: one per month (or per year, in
        // `interval === "year"`) by default, falling back to a few evenly
        // spaced day ticks when the range is under one grid step (one
        // interval-start tick or none).
        parts.push(
            `<line class="grid" x1="${plot.left}" y1="${plot.bottom}"` +
                ` x2="${plot.right}" y2="${plot.bottom}"/>`,
        );
        const ticks =
            interval === "year"
                ? yearStarts(minDate, maxDate)
                : monthStarts(minDate, maxDate);
        if (ticks.length >= 2) {
            let previousYear = null;
            ticks.forEach((t, index) => {
                const date = new Date(t);
                const label =
                    interval === "year"
                        ? String(date.getUTCFullYear())
                        : date.toLocaleDateString(undefined, {
                              timeZone: "UTC",
                              month: "short",
                              ...(date.getUTCFullYear() === previousYear
                                  ? {}
                                  : { year: "numeric" }),
                          });
                previousYear = date.getUTCFullYear();
                parts.push(dateTickLabel(t, index, ticks.length, label));
            });
        } else {
            const dateSteps = 4;
            for (let step = 0; step <= dateSteps; step += 1) {
                const t = minDate + (step / dateSteps) * (maxDate - minDate);
                parts.push(
                    dateTickLabel(
                        t,
                        step,
                        dateSteps + 1,
                        dateLabel(new Date(t)),
                    ),
                );
            }
        }

        // One r line per language (no SD band — see the note above this
        // function).
        for (const one of known) {
            parts.push(
                `<path class="line" data-language="${one.language}" d="M ${one.points
                    .map((p) => `${x(p.date.getTime())},${y(p.rate)}`)
                    .join(" L ")}"/>`,
            );
        }

        svg.innerHTML = parts.join("");
        svg.append(crosshair, focusDot);
        hideHover();
        // `innerHTML` above wiped any highlight classes; restore them (a
        // table-row hover can outlive a resize-triggered re-render).
        applyHighlight(activeLanguage);
    }

    // Crosshair and tooltip: the whole SVG is the hit target, the reader aims
    // at an x position and the nearest point (across every language) answers.
    svg.addEventListener("pointermove", (event) => {
        if (!scale) return;
        const px = event.clientX - svg.getBoundingClientRect().left;
        let nearest = null;
        let nearestSeries = null;
        let bestDistance = Infinity;
        for (const one of scale.known) {
            for (const point of one.points) {
                const distance = Math.abs(scale.x(point.date.getTime()) - px);
                if (distance < bestDistance) {
                    bestDistance = distance;
                    nearest = point;
                    nearestSeries = one;
                }
            }
        }
        if (!nearest) return;
        if (onHoverLanguage) onHoverLanguage(nearestSeries.language);
        const cx = scale.x(nearest.date.getTime());
        const cy = scale.y(nearest.rate);
        crosshair.setAttribute("x1", cx);
        crosshair.setAttribute("x2", cx);
        crosshair.setAttribute("y1", scale.plot.top);
        crosshair.setAttribute("y2", scale.plot.bottom);
        crosshair.style.visibility = "visible";
        focusDot.setAttribute("cx", cx);
        focusDot.setAttribute("cy", cy);
        focusDot.style.visibility = "visible";
        tooltip.textContent =
            `${languageName(nearestSeries.language)}: r = ` +
            `${nearest.rate.toFixed(2)} ± ${(nearest.sd || 0).toFixed(2)}` +
            ` · ${dateLabel(nearest.date)}`;
        tooltip.hidden = false;
        tooltip.style.left = `${Math.max(
            0,
            Math.min(cx + 10, figure.clientWidth - tooltip.offsetWidth - 4),
        )}px`;
        tooltip.style.top = `${Math.max(0, cy - tooltip.offsetHeight - 8)}px`;
    });
    svg.addEventListener("pointerleave", hideHover);
    window.addEventListener("resize", render);

    return {
        // Load every language's history, fetched on page load and again
        // whenever the interval toggle (month/year) re-fetches at a
        // different grid spacing.
        setData(histories, newInterval = "month") {
            interval = newInterval;
            series = histories.map((entry) => ({
                language: entry.language,
                points: entry.points.map((point) => ({
                    date: new Date(point.date),
                    rate: point.rate,
                    sd: point.sd,
                })),
            }));
            render();
        },

        // Highlight `language`'s line and dim the rest, or (for `null`)
        // clear the highlight — the table-row-hover half of the two-way
        // sync `onHoverLanguage` provides for the chart-hover half.
        highlight(language) {
            activeLanguage = language;
            applyHighlight(language);
        },
    };
}

// Stratum line (check page, stratified strategy only): a horizontal axis
// divided into equal segments, one per frequency stratum (leftmost = most
// frequent words). Each answered word is a dot stacked above its stratum's
// segment — filled for "know", hollow for "don't know" — filling upward one
// column at a time and starting a new column alongside once a column is
// full, so the stack stays within a fixed height however many answers a
// segment holds. CSS transitions on `cx`/`cy` slide dots as answers arrive.
export function createStrataChart(figure, svg) {
    const SVG_NS = "http://www.w3.org/2000/svg";
    const VIEW_WIDTH = 500; // The viewBox is a fixed 500×140 strip.
    const MARGIN_X = 20; // Left/right inset, so the outermost dividers show.
    const TOP_MARGIN = 10; // Topmost y a dot's center may reach.
    const BASELINE = 120; // The axis dots stack up from.
    const DOT_RADIUS = 4;
    const PITCH = DOT_RADIUS * 2 + 1.5; // Default row/column spacing.
    const MAX_ROWS = Math.max(1, Math.floor((BASELINE - TOP_MARGIN) / PITCH));

    let nStrata = 0;
    let checkedAtSeed = 0; // Session answers already included in the seed.
    let seeded = false;
    const dividerElements = []; // The segment boundary lines, nStrata + 1.
    const segments = []; // Per stratum: [{ element, know }], insertion order.
    const pending = []; // Live answers arriving before the seed.

    // Segment boundary x positions, `nStrata + 1` of them, equally spaced.
    function boundaries() {
        const span = (VIEW_WIDTH - 2 * MARGIN_X) / nStrata;
        return Array.from(
            { length: nStrata + 1 },
            (_, index) => MARGIN_X + index * span,
        );
    }

    // Re-place everything: dividers at their x, dots filling a column above
    // the baseline (oldest at the bottom) and starting a new column beside
    // it once `MAX_ROWS` is reached, so a heavily answered stratum widens
    // instead of growing off the top of the chart.
    function layoutAll() {
        const xs = boundaries();
        for (const [index, divider] of dividerElements.entries()) {
            divider.setAttribute("x1", xs[index]);
            divider.setAttribute("x2", xs[index]);
        }
        const segmentWidth = xs[1] - xs[0];
        for (const [stratum, dots] of segments.entries()) {
            const center = (xs[stratum] + xs[stratum + 1]) / 2;
            const columns = Math.max(1, Math.ceil(dots.length / MAX_ROWS));
            const colPitch = Math.min(PITCH, segmentWidth / columns);
            const startX = center - (colPitch * (columns - 1)) / 2;
            for (const [index, dot] of dots.entries()) {
                const column = Math.floor(index / MAX_ROWS);
                const row = index % MAX_ROWS;
                dot.element.setAttribute("cx", startX + column * colPitch);
                dot.element.setAttribute(
                    "cy",
                    BASELINE - DOT_RADIUS - row * PITCH,
                );
            }
        }
    }

    // Create a dot without adding it to the document: the caller runs
    // `layoutAll` first, so the dot pops up in place instead of sliding in.
    function place(stratum, know) {
        if (stratum == null || stratum < 0 || stratum >= nStrata) return null;
        const dot = document.createElementNS(SVG_NS, "circle");
        dot.setAttribute("class", `dot ${know ? "know" : "dont"}`);
        dot.setAttribute("r", DOT_RADIUS);
        segments[stratum].push({ element: dot, know });
        return dot;
    }

    function add(stratum, know) {
        const dot = place(stratum, know);
        if (!dot) return;
        layoutAll();
        svg.append(dot);
    }

    // Remove the segment's most recent dot of that kind (for an undo).
    function remove(stratum, know) {
        if (stratum == null || stratum < 0 || stratum >= nStrata) return;
        const dots = segments[stratum];
        for (let index = dots.length - 1; index >= 0; index -= 1) {
            if (dots[index].know === know) {
                dots[index].element.remove();
                dots.splice(index, 1);
                layoutAll();
                return;
            }
        }
    }

    return {
        // Draw the axis and the whole history's dots, then replay the
        // answers this session recorded while the seed was loading (the
        // first `checkedNow` of them are already inside the seed).
        setSeed(answers, total, checkedNow) {
            nStrata = total;
            checkedAtSeed = checkedNow;
            segments.length = 0;
            dividerElements.length = 0;
            svg.replaceChildren();

            const baseline = document.createElementNS(SVG_NS, "line");
            baseline.setAttribute("class", "baseline");
            baseline.setAttribute("x1", MARGIN_X);
            baseline.setAttribute("x2", VIEW_WIDTH - MARGIN_X);
            baseline.setAttribute("y1", BASELINE);
            baseline.setAttribute("y2", BASELINE);
            svg.append(baseline);

            // One divider more than there are segments, marking every
            // boundary between (and around) them.
            for (let boundary = 0; boundary <= nStrata; boundary += 1) {
                const divider = document.createElementNS(SVG_NS, "line");
                divider.setAttribute("class", "divider");
                divider.setAttribute("y1", TOP_MARGIN);
                divider.setAttribute("y2", BASELINE);
                svg.append(divider);
                dividerElements.push(divider);
                if (boundary < nStrata) segments.push([]);
            }
            // One layout for the whole history, then attach: dots enter the
            // document already in position.
            const dots = [];
            for (const answer of answers) {
                const dot = place(answer.stratum, answer.know);
                if (dot) dots.push(dot);
            }
            layoutAll();
            svg.append(...dots);
            seeded = true;
            for (const event of pending) {
                if (event.checked <= checkedAtSeed) continue;
                if (event.add) add(event.stratum, event.know);
                else remove(event.stratum, event.know);
            }
            pending.length = 0;
            figure.hidden = false;
        },
        noteAnswer(checked, stratum, know) {
            if (stratum == null) return;
            if (!seeded) {
                pending.push({ checked, add: true, stratum, know });
                return;
            }
            add(stratum, know);
        },
        noteUndo(checked, stratum, know) {
            if (stratum == null) return;
            if (!seeded) {
                pending.push({ checked, add: false, stratum, know });
                return;
            }
            remove(stratum, know);
        },
    };
}
