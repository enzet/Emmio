// Lexicon selection-strategy icons: private-use codepoints in the "Emmio"
// icon font (`data/codepoints.txt`, `base.css`'s `@font-face`).
const STRATEGY_ICON_CHARS = {
    frequency: "\uE001",
    stratified: "\uE002",
    logistic: "\uE003",
    threshold: "\uE004",
};

// A strategy's icon glyph plus a trailing space, or "" if it has none (e.g.
// uniform random). Pair with the `.strategy-text` CSS class in base.css.
export function strategyIconPrefix(strategyValue) {
    const char = STRATEGY_ICON_CHARS[strategyValue];
    return char ? char + " " : "";
}

// Format an ISO timestamp as a short, human "time ago" (falls back to a date).
export function relativeTime(iso) {
    const days = Math.floor((Date.now() - new Date(iso)) / 86400000);
    if (days <= 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 30) return `${days} days ago`;
    return new Date(iso).toLocaleDateString();
}

// Format a positive duration in milliseconds as a short countdown, using the
// two largest non-zero units (e.g. "3d 4h", "5h 12m", "20m"). Returns "now"
// for non-positive durations.
export function formatCountdown(ms) {
    if (ms <= 0) return "now";
    const days = Math.floor(ms / 86400000);
    const hours = Math.floor((ms % 86400000) / 3600000);
    const minutes = Math.floor((ms % 3600000) / 60000);
    if (days > 0) return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
    if (hours > 0) return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
    return `${Math.max(minutes, 1)}m`;
}

// Turn an ISO language code (e.g. `fr`) into a human name (`French`). Falls
// back to the code itself for unknown or malformed codes.
const languageNames = new Intl.DisplayNames(["en"], { type: "language" });

export function languageName(code) {
    try {
        return languageNames.of(code) || code;
    } catch {
        return code;
    }
}

// Format a rate estimate with its standard deviation, e.g. `5.5 ± 0.6`; an
// em dash when there is no estimate yet.
export function formatRate(rate, sd, digits) {
    if (rate === null || rate === undefined) return "—";
    let text = rate.toFixed(digits);
    if (sd !== null && sd !== undefined) text += ` ± ${sd.toFixed(digits)}`;
    return text;
}

// Emmio-specific language level derived from the lexicon rate `r`: each
// level spans one unit of `r`.
export function emmioLevel(rate, cell) {
    var level = "";
    if (rate === null || rate < 2) {
        cell.append("< ");
        level = "A1";
    } else if (rate < 3) {
        level = "A1";
    } else if (rate < 4) {
        level = "A2";
    } else if (rate < 5) {
        level = "B1";
    } else if (rate < 6) {
        level = "B2";
    } else if (rate < 7) {
        level = "C1";
    } else if (rate < 8) {
        level = "C2";
    } else {
        cell.append("> ");
        level = "C2";
    }
    var span = document.createElement("span");
    span.setAttribute("class", "abbr");
    span.textContent = level;
    cell.append(span);
}

// Append a `<dt>`/`<dd>` pair to `container` for each `[label, value,
// className, onClick]` row (`className` and `onClick` are optional). Shared
// by the lexicon, course, and profile detail pages. A row with `onClick`
// renders its value as a button instead of plain text — e.g. the lexicon
// page's "Known"/"Don't know" counts, which open that word list.
export function renderDefinitionList(container, rows) {
    for (const [label, value, className, onClick] of rows) {
        const term = document.createElement("dt");
        term.textContent = label;
        const description = document.createElement("dd");
        if (className) description.className = className;
        if (onClick) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "dd-link";
            button.textContent = value;
            button.addEventListener("click", onClick);
            description.appendChild(button);
        } else {
            description.textContent = value;
        }
        container.append(term, description);
    }
}

// A small animated "loading" indicator: three dots pulsing in sequence
// (styled by `.dots` in base.css). Returns a fresh element each call. The
// dots are decorative; the wrapper announces "Loading" to readers.
export function loadingDots() {
    const dots = document.createElement("span");
    dots.className = "dots";
    dots.setAttribute("role", "status");
    dots.setAttribute("aria-label", "Loading");
    for (let i = 0; i < 3; i += 1) {
        const dot = document.createElement("span");
        dot.setAttribute("aria-hidden", "true");
        dots.append(dot);
    }
    return dots;
}

// A course/learning/lexicon identifier (as opposed to its human-facing
// name), rendered in monospace so it reads as a code, not prose.
export function identifierSpan(id) {
    const span = document.createElement("span");
    span.className = "identifier";
    span.textContent = id;
    return span;
}

// Fill a `<select>` with one `<option>` per language, sorted by display name.
// `entries` is a list of API rows carrying a `language` ISO code; `selectCode`
// optionally preselects the matching option.
export function fillLanguageSelect(select, entries, selected) {
    // `selected` preselects options: a single code or a Set of codes.
    const isSelected =
        selected instanceof Set
            ? (code) => selected.has(code)
            : (code) => code === selected;
    entries
        .map((entry) => ({
            code: entry.language,
            name: languageName(entry.language),
        }))
        .sort((a, b) => a.name.localeCompare(b.name))
        .forEach((entry) => {
            const option = document.createElement("option");
            option.value = entry.code;
            option.textContent = entry.name;
            if (isSelected(entry.code)) option.selected = true;
            select.appendChild(option);
        });
}
