"use strict";

// Minimal vanilla-JS client for the Emmio API. Holds the access token in
// localStorage and attaches it as a bearer token on each request. No build
// step, no framework; pages dispatch on `<body data-page="...">`.

const API = "/api/v1";
const TOKEN_KEY = "emmio_token";

// Lexicon selection-strategy icons: private-use codepoints in the "Emmio"
// icon font (see `data/codepoints.txt`, `base.css`'s `@font-face`). Strategies
// without a glyph here (uniform random, most frequent first) show no icon.
const STRATEGY_ICON_CHARS = {
    frequency: "\uE001",
    stratified: "\uE002",
    logistic: "\uE003",
    threshold: "\uE004",
};

// A strategy's icon glyph plus a trailing space, or "" if it has none. Pair
// with the `.strategy-text` CSS class so the glyph actually renders as an
// icon (see the comment above `.strategy-text` in base.css).
function strategyIconPrefix(strategyValue) {
    const char = STRATEGY_ICON_CHARS[strategyValue];
    return char ? char + " " : "";
}

const getToken = () => localStorage.getItem(TOKEN_KEY);
const setToken = (token) => localStorage.setItem(TOKEN_KEY, token);
const clearToken = () => localStorage.removeItem(TOKEN_KEY);

// Call the API. `form` sends URL-encoded fields (for OAuth2 login); `body`
// sends JSON. A 401 clears the token and returns to the login page.
async function api(path, { method = "GET", body, form } = {}) {
    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    let payload;
    if (form) {
        payload = new URLSearchParams(form);
    } else if (body) {
        headers["Content-Type"] = "application/json";
        payload = JSON.stringify(body);
    }

    const response = await fetch(API + path, {
        method,
        headers,
        body: payload,
    });
    if (response.status === 401) {
        clearToken();
        location.href = "login";
        throw new Error("Not authenticated");
    }
    return response;
}

function requireAuth() {
    if (!getToken()) location.href = "login";
}

// Format an ISO timestamp as a short, human "time ago" (falls back to a date).
function relativeTime(iso) {
    const days = Math.floor((Date.now() - new Date(iso)) / 86400000);
    if (days <= 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 30) return `${days} days ago`;
    return new Date(iso).toLocaleDateString();
}

// Format a positive duration in milliseconds as a short countdown, using the
// two largest non-zero units (e.g. "3d 4h", "5h 12m", "20m"). Returns "now"
// for non-positive durations.
function formatCountdown(ms) {
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
function languageName(code) {
    try {
        return languageNames.of(code) || code;
    } catch {
        return code;
    }
}

// Emmio-specific language level derived directly from the lexicon rate `r`:
// each level spans one unit of `r`. Rates below A1 or a missing rate return an
// em dash.
// Format a rate estimate with its standard deviation, e.g. `5.5 ± 0.6`; an
// em dash when there is no estimate yet.
function formatRate(rate, sd, digits) {
    if (rate === null || rate === undefined) return "—";
    let text = rate.toFixed(digits);
    if (sd !== null && sd !== undefined) text += ` ± ${sd.toFixed(digits)}`;
    return text;
}

function emmioLevel(rate, cell) {
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

// Append a `<dt>`/`<dd>` pair to `container` for each `[label, value]` row.
// Shared by the lexicon, course, and profile detail pages.
function renderDefinitionList(container, rows) {
    for (const [label, value, className] of rows) {
        const term = document.createElement("dt");
        term.textContent = label;
        const description = document.createElement("dd");
        description.textContent = value;
        if (className) description.className = className;
        container.append(term, description);
    }
}

// A small animated "loading" indicator: three dots pulsing in sequence (styled
// by `.dots` in base.css). Returns a fresh element each call, so it can be
// dropped into the word, sentence, or translation slot while it loads. The
// dots themselves are decorative; the wrapper announces "Loading" to readers.
function loadingDots() {
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
function identifierSpan(id) {
    const span = document.createElement("span");
    span.className = "identifier";
    span.textContent = id;
    return span;
}

// Fill a `<select>` with one `<option>` per language, sorted by display name.
// `entries` is a list of API rows carrying a `language` ISO code; `selectCode`
// optionally preselects the matching option.
function fillLanguageSelect(select, entries, selected) {
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

// Public landing page. Forward an already-signed-in visitor straight to the
// dashboard, so returning users don't land on the marketing page.

function initLanding() {
    if (getToken()) location.href = "index";
}

// Login page.

function initLogin() {
    if (getToken()) {
        location.href = "index";
        return;
    }

    document
        .getElementById("login-form")
        .addEventListener("submit", async (e) => {
            e.preventDefault();
            const error = document.getElementById("login-error");
            error.textContent = "";
            const data = new FormData(e.target);
            const response = await api("/auth/login", {
                method: "POST",
                form: {
                    username: data.get("email"),
                    password: data.get("password"),
                    remember: e.target.remember.checked ? "true" : "false",
                },
            });
            if (response.ok) {
                const { access_token } = await response.json();
                setToken(access_token);
                location.href = "index";
            } else {
                error.textContent = "Incorrect email or password.";
            }
        });
}

// Registration page.

function initRegister() {
    if (getToken()) {
        location.href = "index";
        return;
    }

    document
        .getElementById("register-form")
        .addEventListener("submit", async (e) => {
            e.preventDefault();
            const message = document.getElementById("register-message");
            message.textContent = "";
            const data = new FormData(e.target);
            const response = await api("/auth/register", {
                method: "POST",
                body: {
                    user_id: data.get("user_id"),
                    name: data.get("name"),
                    email: data.get("email"),
                    password: data.get("password"),
                },
            });
            if (response.ok) {
                message.textContent = "Registered. You can log in now.";
                e.target.reset();
            } else {
                const { detail } = await response.json().catch(() => ({}));
                message.textContent = detail || "Registration failed.";
            }
        });
}

// Home / dashboard page.

async function initHome() {
    requireAuth();

    const status = document.getElementById("languages-status");
    const table = document.getElementById("languages-table");
    const rows = document.getElementById("languages-rows");

    // `/me/languages` estimates every main lexicon's rate, which can take up
    // to a second each on a cache miss (see the server's
    // `_row_rate_estimate`) — too slow to block the table's first paint on.
    // Fetch the cheap parts first (language identity, from
    // `/me/languages/summary`, plus courses) so the table can render
    // immediately with placeholders in the rate/level/lexicon columns; the
    // real rate estimate is fetched after and fills those in once ready.
    const [summaryResponse, coursesResponse] = await Promise.all([
        api("/me/languages/summary"),
        api("/me/courses"),
    ]);
    const summaries = summaryResponse.ok ? await summaryResponse.json() : [];
    const courses = coursesResponse.ok ? await coursesResponse.json() : [];
    const coursesByLanguage = new Map();
    for (const course of courses) {
        const list = coursesByLanguage.get(course.language) || [];
        list.push(course);
        coursesByLanguage.set(course.language, list);
    }

    // Nothing yet: welcome the user and offer to create their first lexicon.
    // The dashboard shows for any language the user has a main lexicon *or* a
    // course for.
    if (summaries.length === 0 && courses.length === 0) {
        document.getElementById("welcome").hidden = false;
        return;
    }
    document.getElementById("languages").hidden = false;
    status.textContent = "";
    table.hidden = false;

    // Cells still waiting on their rate estimate, keyed by language, so the
    // follow-up `/me/languages` response can fill them in without
    // re-rendering the whole table.
    const pendingCells = new Map();

    // Render one language row. `summary` is its main-lexicon identity (from
    // `/me/languages/summary`) or `null` when the language only has courses;
    // `courseList` are its courses.
    function renderLanguageRow(language, summary, courseList) {
        const row = document.createElement("tr");

        const nameCell = document.createElement("td");
        const nameLink = document.createElement("a");
        nameLink.href = `language?language=${encodeURIComponent(language)}`;
        const code = document.createElement("span");
        code.className = "language-code";
        code.textContent = language;
        nameLink.appendChild(code);
        nameLink.appendChild(
            document.createTextNode(languageName(language)),
        );
        nameCell.appendChild(nameLink);
        row.appendChild(nameCell);

        const rateCell = document.createElement("td");
        rateCell.textContent = summary ? "…" : "—";
        rateCell.style.fontVariantNumeric = "tabular-nums";
        rateCell.style.textAlign = "right";
        row.appendChild(rateCell);

        // Emmio-specific language level, derived from the rate once it
        // arrives.
        const levelCell = document.createElement("td");
        levelCell.textContent = summary ? "…" : "—";
        levelCell.style.fontVariantNumeric = "tabular-nums";
        levelCell.style.textAlign = "right";
        row.appendChild(levelCell);

        // Lexicon column: a link to the main lexicon, then a "Check" button
        // while checking is available, otherwise the time until it unlocks
        // again (the precision goal was met, and rechecking is paused for a
        // week). The check-available state isn't known until the rate
        // estimate arrives, so the link itself is filled in then too.
        const lexiconCell = document.createElement("td");
        row.appendChild(lexiconCell);

        if (summary) {
            pendingCells.set(language, { rateCell, levelCell, lexiconCell });
        }

        // Courses for this language, each linking to its detail page; a
        // course with no learnings yet offers to add one directly.
        const coursesCell = document.createElement("td");
        coursesCell.className = "courses-cell";
        for (const course of courseList) {
            if (course.learning_count > 0) {
                const link = document.createElement("a");
                link.href = `course?course=${encodeURIComponent(
                    course.course_id,
                )}`;
                link.textContent = course.name;
                coursesCell.appendChild(link);
            } else {
                const empty = document.createElement("span");
                empty.className = "course-empty";
                empty.appendChild(
                    document.createTextNode(`${course.name} (`),
                );
                const add = document.createElement("a");
                add.href = `new-learning?course=${encodeURIComponent(
                    course.course_id,
                )}`;
                add.textContent = "+ add a learning";
                empty.appendChild(add);
                empty.appendChild(document.createTextNode(")"));
                coursesCell.appendChild(empty);
            }
        }
        row.appendChild(coursesCell);

        rows.appendChild(row);
        return row;
    }

    // Languages with a main lexicon first (order to be refined by rate once
    // it arrives), then the course-only ones, alphabetically. `sectionEnd`
    // marks the boundary between the two groups, so the rated rows can later
    // be re-sorted in place (moved before it) without disturbing the
    // course-only rows after it.
    const rated = new Set();
    const ratedRows = new Map();
    for (const summary of summaries) {
        rated.add(summary.language);
        ratedRows.set(
            summary.language,
            renderLanguageRow(
                summary.language,
                summary,
                coursesByLanguage.get(summary.language) || [],
            ),
        );
    }
    const sectionEnd = document.createComment("course-only");
    rows.appendChild(sectionEnd);
    const courseOnly = [...coursesByLanguage.keys()]
        .filter((language) => !rated.has(language))
        .sort((a, b) => languageName(a).localeCompare(languageName(b)));
    for (const language of courseOnly) {
        renderLanguageRow(language, null, coursesByLanguage.get(language));
    }

    // Fill in the rate/level/lexicon-check columns, and re-sort the rated
    // rows by rate (descending, matching the server's own ordering), once
    // the slower per-lexicon estimate is ready.
    api("/me/languages").then(async (response) => {
        if (!response.ok) return;
        const languages = await response.json();
        const sorted = [...languages].sort(
            (a, b) => (b.rate ?? -Infinity) - (a.rate ?? -Infinity),
        );
        for (const entry of sorted) {
            const cells = pendingCells.get(entry.language);
            if (!cells) continue;
            const { rateCell, levelCell, lexiconCell } = cells;

            rateCell.textContent = formatRate(entry.rate, entry.sd, 2);

            levelCell.textContent = "";
            emmioLevel(entry.rate, levelCell);

            const lexiconLink = document.createElement("a");
            lexiconLink.className = "lexicon-link strategy-text";
            lexiconLink.href = `lexicon?lexicon=${encodeURIComponent(
                entry.lexicon_id,
            )}`;
            if (entry.selection) {
                lexiconLink.append(strategyIconPrefix(entry.selection));
            }
            lexiconLink.append(identifierSpan(entry.lexicon_id));
            if (entry.check_available) {
                const check = document.createElement("sup");
                check.setAttribute("class", "notification")
                // Possible link:
                // `check?lexicon=${encodeURIComponent(entry.lexicon_id)}`.
                check.appendChild(document.createTextNode("⚫︎"));
                lexiconLink.appendChild(check);
            }
            lexiconCell.replaceChildren(lexiconLink);

            // Move this row right before the course-only section, in rate
            // order.
            rows.insertBefore(ratedRows.get(entry.language), sectionEnd);
        }
    });

    // Vocabulary-level history of the main lexicons, one line per language —
    // drawn client-side by the same mechanism as the check page's
    // convergence chart, rather than a server-rendered image.
    const historyResponse = await api("/me/lexicons/history");
    if (historyResponse.ok) {
        const chart = createLanguageHistoryChart(
            document.getElementById("lexicon-history"),
            document.getElementById("lexicon-history-svg"),
            document.getElementById("lexicon-history-tooltip"),
            document.getElementById("lexicon-history-legend"),
        );
        chart.setData(await historyResponse.json());
    }
}

// Language page: every lexicon and course for one language, gathered in one
// place. The dashboard links each language name here instead of listing
// everything inline.
async function initLanguage() {
    requireAuth();

    const language = new URLSearchParams(location.search).get("language");
    document.getElementById("language-heading").textContent =
        `Language: ${languageName(language)}`;
    document.getElementById("add-lexicon-link").href =
        `new-lexicon?language=${encodeURIComponent(language)}`;

    const lexiconsStatus = document.getElementById("lexicons-status");
    const lexiconTable = document.getElementById("lexicon-table");
    const lexiconRows = document.getElementById("lexicon-rows");
    const lexiconResponse = await api("/me/lexicons");
    const lexicons = (
        lexiconResponse.ok ? await lexiconResponse.json() : []
    ).filter((lexicon) => lexicon.language === language);

    if (lexicons.length === 0) {
        lexiconsStatus.textContent = "No lexicons for this language yet.";
    } else {
        lexiconsStatus.textContent = "";
        lexiconTable.hidden = false;
    }
    for (const lexicon of lexicons) {
        const row = document.createElement("tr");

        const idCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = `lexicon?lexicon=${encodeURIComponent(
            lexicon.lexicon_id,
        )}`;
        // A leading star marks the main lexicon for its language.
        if (lexicon.is_main) link.append("★ ");
        if (lexicon.name) {
            link.append(lexicon.name);
            link.title = lexicon.lexicon_id;
        } else {
            link.append(identifierSpan(lexicon.lexicon_id));
        }
        idCell.appendChild(link);
        row.appendChild(idCell);

        const selectionCell = document.createElement("td");
        selectionCell.className = "strategy-text";
        selectionCell.textContent = lexicon.selection
            ? strategyIconPrefix(lexicon.selection) + lexicon.selection
            : "";
        row.appendChild(selectionCell);

        for (const value of [
            formatRate(lexicon.rate, lexicon.sd, 2),
            lexicon.words,
        ]) {
            const cell = document.createElement("td");
            cell.textContent = value;
            row.appendChild(cell);
        }

        lexiconRows.appendChild(row);
    }

    const coursesStatus = document.getElementById("courses-status");
    const courseTable = document.getElementById("course-table");
    const courseRows = document.getElementById("course-rows");
    const courseResponse = await api("/me/courses");
    const courses = (
        courseResponse.ok ? await courseResponse.json() : []
    ).filter((course) => course.language === language);

    if (courses.length === 0) {
        coursesStatus.textContent = "No courses for this language yet.";
    } else {
        coursesStatus.textContent = "";
        courseTable.hidden = false;
    }
    for (const course of courses) {
        const row = document.createElement("tr");

        const idCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = `course?course=${encodeURIComponent(course.course_id)}`;
        link.textContent = course.name;
        idCell.appendChild(link);
        row.appendChild(idCell);

        const learningCountCell = document.createElement("td");
        learningCountCell.textContent = course.learning_count;
        row.appendChild(learningCountCell);

        courseRows.appendChild(row);
    }
}

// Add-a-lexicon / add-a-course page.
//
// Each lives on its own page (`new-lexicon.html` / `new-course.html`) with
// the form markup written directly in the HTML; these just wire it up.
async function initNewLexicon() {
    requireAuth();
    await setupCreateLexicon(
        "add-lexicon-form",
        "add-lexicon-language",
        "add-status",
    );
}

async function initNewCourse() {
    requireAuth();
    await setupCreateCourse(
        "add-course-form",
        "add-course-language",
        "add-course-status",
    );
}

async function initNewLearning() {
    requireAuth();
    const courseId = new URLSearchParams(location.search).get("course");
    document.getElementById("back-to-course").href =
        `course?course=${encodeURIComponent(courseId)}`;
    await setupCreateLearning(
        courseId,
        "add-learning-form",
        "add-learning-status",
    );
}

// Skin a native strategy <select> with a decorative icon+label overlay: the
// closed box shows the icon (the overlay mirrors the selected option), but
// the actual <option> text stays icon-free, so the *open* dropdown list never
// shows the icon glyph. That's deliberate — on macOS, Safari and Chrome
// render the open list as a native Cocoa popup that ignores the page's
// @font-face and falls back to a "missing glyph" box for the icon font's
// private-use codepoints, while the closed box (drawn by the page itself)
// renders it fine. The overlay is `aria-hidden` and `pointer-events: none`,
// so it's purely visual: the real <select> still drives all keyboard/mouse
// interaction, focus, and the accessible name.
function addStrategyOverlay(select) {
    const wrapper = document.createElement("span");
    wrapper.className = "strategy-picker";
    select.replaceWith(wrapper);
    wrapper.appendChild(select);

    const overlay = document.createElement("span");
    overlay.className = "strategy-picker-overlay strategy-text";
    overlay.setAttribute("aria-hidden", "true");
    wrapper.appendChild(overlay);

    // A bare <select> gets the browser's own small control font, distinct
    // from (usually smaller than) the page's ambient font the overlay would
    // otherwise inherit; match it so the overlay's icon-prefixed text is the
    // same size the select auto-sized its (icon-free) box for.
    const selectStyle = getComputedStyle(select);
    overlay.style.fontSize = selectStyle.fontSize;
    overlay.style.lineHeight = selectStyle.lineHeight;

    function update() {
        const option = select.options[select.selectedIndex];
        overlay.textContent = option
            ? strategyIconPrefix(option.value) + option.textContent
            : "";
    }

    // The select auto-sizes to fit its own (icon-free) option text, so its
    // box can be too narrow for the overlay's longer icon-prefixed version.
    // Measure how much every option actually needs (rather than guessing a
    // fixed padding) and widen the select by the worst case, so this keeps
    // working if the strategy labels or the icon set change.
    let maxTextWidth = 0;
    for (const option of select.options) {
        overlay.textContent = strategyIconPrefix(option.value) + option.textContent;
        maxTextWidth = Math.max(maxTextWidth, overlay.scrollWidth);
    }
    const overlayStyle = getComputedStyle(overlay);
    const needed =
        maxTextWidth + parseFloat(overlayStyle.left) + parseFloat(overlayStyle.right);
    const shortfall = needed - select.getBoundingClientRect().width;
    if (shortfall > 0) {
        select.style.paddingLeft = `calc(${selectStyle.paddingLeft} + ${Math.ceil(shortfall) + 2}px)`;
    }

    select.addEventListener("change", update);
    update();
}

// Wire up a "create lexicon" form: fill its language selector from the
// available frequency-list languages, and on submit create the lexicon (which
// is set as main, with the chosen selection strategy) and open it. The
// frequency-list picker is re-filled whenever the language changes, since the
// set of matching lists differs per language.
async function setupCreateLexicon(formId, selectId, statusId) {
    const form = document.getElementById(formId);
    const select = document.getElementById(selectId);
    const frequencyListSelect = form.querySelector(".lexicon-frequency-list");
    const targets = form.querySelector(".translation-languages");
    const selection = form.querySelector(".lexicon-selection");
    const createStatus = document.getElementById(statusId);

    const [response, frequencyListResponse, targetResponse, strategyResponse] =
        await Promise.all([
            api("/lexicon-languages"),
            api("/frequency-lists"),
            api("/translation-languages"),
            api("/lexicon-strategies"),
        ]);
    const available = await response.json();
    if (available.length === 0) {
        createStatus.textContent =
            "No languages with a frequency list and sentences are available " +
            "yet.";
        select.disabled = true;
        form.querySelector("button").disabled = true;
        return;
    }

    // Arriving from a language page preselects that language, rather than
    // making the user pick it again from scratch.
    const linkedLanguage = new URLSearchParams(location.search).get(
        "language",
    );
    fillLanguageSelect(
        select,
        available,
        available.some((entry) => entry.language === linkedLanguage)
            ? linkedLanguage
            : undefined,
    );

    const frequencyLists = await frequencyListResponse.json();
    fillFrequencyListSelect(frequencyListSelect, frequencyLists, select.value);
    select.addEventListener("change", () => {
        fillFrequencyListSelect(
            frequencyListSelect,
            frequencyLists,
            select.value,
        );
    });

    // Fill the "translate into" picker with every known language; preselect
    // English as the most common target.
    fillLanguageSelect(targets, await targetResponse.json(), "en");

    // Fill the selection-strategy picker from the server's single source of
    // truth; the first strategy (frequency-weighted random) is the default.
    for (const strategy of await strategyResponse.json()) {
        const option = document.createElement("option");
        option.value = strategy.value;
        option.textContent = strategy.label;
        selection.appendChild(option);
    }
    addStrategyOverlay(selection);

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const translationLanguages = Array.from(
            targets.selectedOptions,
            (option) => option.value,
        );
        if (translationLanguages.length === 0) {
            createStatus.textContent =
                "Pick at least one language to translate into.";
            return;
        }
        createStatus.textContent = "Creating…";
        const result = await api("/me/lexicons", {
            method: "POST",
            body: {
                language: select.value,
                translation_languages: translationLanguages,
                selection: selection.value,
                frequency_list: decodeFrequencyListValue(
                    frequencyListSelect.value,
                ),
            },
        });
        if (result.ok) {
            const { lexicon_id } = await result.json();
            location.href = `lexicon?lexicon=${encodeURIComponent(
                lexicon_id,
            )}`;
        } else {
            const { detail } = await result.json().catch(() => ({}));
            createStatus.textContent = detail || "Could not create lexicon.";
        }
    });
}

// A frequency-list option is identified by `id` plus `year` (only
// `frequency_words` options need the year, to tell cached releases apart),
// so encode both into the <select> value as a single string.
function encodeFrequencyListValue(option) {
    return `${option.id}::${option.year ?? ""}`;
}

function decodeFrequencyListValue(value) {
    const [id, year] = value.split("::");
    return { id, year: year ? Number(year) : null };
}

// Fill the "draw new words from" picker with the frequency lists available
// for `language`, starring and preselecting the one creation would pick
// automatically if left untouched. Called on load and again whenever the
// lexicon's or learning's language changes, since the set of matching lists
// differs per language.
function fillFrequencyListSelect(select, frequencyLists, language) {
    select.innerHTML = "";
    for (const option of frequencyLists) {
        if (option.language !== language) continue;
        const el = document.createElement("option");
        el.value = encodeFrequencyListValue(option);
        el.textContent = (option.is_default ? "★ " : "") + option.name;
        if (option.is_default) el.selected = true;
        select.appendChild(el);
    }
}

// Fill a learning's lexicon picker (either "skip known words" or "ask about
// unseen words") with the caller's lexicons for `language`, plus a leading
// "none" option; `selected` (a lexicon id, if any) preselects an option.
// Called on load and, on the creation page, again whenever the learning's
// language changes, since the set of matching lexicons differs per language.
function fillLearningLexiconSelect(select, lexicons, language, selected) {
    select.innerHTML = "";
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "(none)";
    if (!selected) none.selected = true;
    select.appendChild(none);
    for (const lexicon of lexicons) {
        if (lexicon.language !== language) continue;
        const option = document.createElement("option");
        option.value = lexicon.lexicon_id;
        option.textContent =
            (lexicon.is_main ? "★ " : "") +
            (lexicon.name || lexicon.lexicon_id);
        if (lexicon.lexicon_id === selected) option.selected = true;
        select.appendChild(option);
    }
}

// Render a "question types" checkbox group into `container`: one checkbox
// per type the server supports, checked per `checkedTypes` (a `Set` of
// values). Shared by learning creation (defaults to every type checked) and
// learning settings (defaults to the learning's current `question_types`).
function renderQuestionTypeCheckboxes(
    container,
    idPrefix,
    types,
    checkedTypes,
) {
    container.innerHTML = "";
    for (const type of types) {
        const label = document.createElement("label");
        label.className = "checkbox";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.id = `${idPrefix}-${type.value}`;
        input.value = type.value;
        input.checked = checkedTypes.has(type.value);
        label.appendChild(input);
        label.appendChild(document.createTextNode(` ${type.label}`));
        container.appendChild(label);
    }
}

// Read back which question types are checked in a group rendered above.
function checkedQuestionTypes(container) {
    return Array.from(
        container.querySelectorAll("input[type=checkbox]:checked"),
        (input) => input.value,
    );
}

// Wire up an "add a course" form: just a language and a name. A course is an
// empty language-level shell — languages offered are the union of ones that
// can host a word learning (`/lexicon-languages`) or a symbol learning
// (`/alphabet-languages`), so every offered language can have at least one
// learning added to it afterward. On submit, creates the course and opens
// its (empty) detail page.
async function setupCreateCourse(formId, selectId, statusId) {
    const form = document.getElementById(formId);
    const select = document.getElementById(selectId);
    const nameInput = form.querySelector(".course-name");
    const submitButton = form.querySelector("button[type=submit]");
    const createStatus = document.getElementById(statusId);

    const [wordLanguageResponse, alphabetLanguageResponse] =
        await Promise.all([
            api("/lexicon-languages"),
            api("/alphabet-languages"),
        ]);
    const byLanguage = new Map();
    for (const entry of await wordLanguageResponse.json()) {
        byLanguage.set(entry.language, entry);
    }
    for (const entry of await alphabetLanguageResponse.json()) {
        if (!byLanguage.has(entry.language)) byLanguage.set(entry.language, entry);
    }
    const available = [...byLanguage.values()];

    if (available.length === 0) {
        createStatus.textContent = "No languages are available yet.";
        select.disabled = true;
        submitButton.disabled = true;
        return;
    }
    fillLanguageSelect(select, available);

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        createStatus.textContent = "Creating…";
        const result = await api("/me/courses", {
            method: "POST",
            body: {
                language: select.value,
                name: nameInput.value.trim() || languageName(select.value),
            },
        });
        if (result.ok) {
            const { course_id } = await result.json();
            location.href = `course?course=${encodeURIComponent(course_id)}`;
        } else {
            const { detail } = await result.json().catch(() => ({}));
            createStatus.textContent = detail || "Could not create course.";
        }
    });
}

// Wire up an "add a learning" form for an existing course. A `word` learning
// (the default) draws new words from a frequency list, needs translation
// targets, and can reference lexicons; a `symbol` learning drills the
// language's own alphabet instead and needs none of that — switching the
// "What to learn" radio hides the word-only fields. The course's language is
// fixed, so only the learning type whose language support the course's
// language actually has is offered. On submit, adds the learning and opens
// its learning session.
async function setupCreateLearning(courseId, formId, statusId) {
    const form = document.getElementById(formId);
    const createStatus = document.getElementById(statusId);
    const courseResponse = await api(
        `/me/courses/${encodeURIComponent(courseId)}`,
    );
    if (!courseResponse.ok) {
        createStatus.textContent = "Unknown course.";
        form.hidden = true;
        return;
    }
    const course = await courseResponse.json();
    document.getElementById("add-learning-heading").textContent =
        `Add a learning: ${course.name}`;

    const learningTypeInputs = Array.from(
        form.querySelectorAll(".learning-type"),
    );
    const wordFields = form.querySelector(".learning-word-fields");
    const targets = form.querySelector(".translation-languages");
    const frequencyListSelect = form.querySelector(
        ".learning-frequency-list",
    );
    const lexiconSelect = form.querySelector(".learning-lexicon");
    const askLexiconSelect = form.querySelector(".learning-ask-lexicon");
    const nameInput = form.querySelector(".learning-name");
    const maxForDayInput = form.querySelector(".learning-max-for-day");
    const playAudioInput = form.querySelector(".learning-play-audio");
    const questionTypesContainer = form.querySelector(
        ".learning-question-types",
    );
    const submitButton = form.querySelector("button[type=submit]");

    const [
        wordLanguageResponse,
        alphabetLanguageResponse,
        targetResponse,
        frequencyListResponse,
        lexiconResponse,
        questionTypeResponse,
    ] = await Promise.all([
        api("/lexicon-languages"),
        api("/alphabet-languages"),
        api("/translation-languages"),
        api("/frequency-lists"),
        api("/me/lexicons"),
        api("/question-types"),
    ]);
    const supportsWord = (await wordLanguageResponse.json()).some(
        (entry) => entry.language === course.language,
    );
    const supportsSymbol = (await alphabetLanguageResponse.json()).some(
        (entry) => entry.language === course.language,
    );

    fillLanguageSelect(targets, await targetResponse.json(), "en");

    // Every question type is allowed unless the user narrows it down.
    const questionTypes = await questionTypeResponse.json();
    renderQuestionTypeCheckboxes(
        questionTypesContainer,
        "add-learning-question-type",
        questionTypes,
        new Set(questionTypes.map((type) => type.value)),
    );

    const frequencyLists = await frequencyListResponse.json();
    const lexicons = await lexiconResponse.json();

    for (const input of learningTypeInputs) {
        if (input.value === "word") input.disabled = !supportsWord;
        if (input.value === "symbol") input.disabled = !supportsSymbol;
    }
    if (!supportsWord && supportsSymbol) {
        form.querySelector(".learning-type[value=symbol]").checked = true;
    }
    if (!supportsWord && !supportsSymbol) {
        createStatus.textContent =
            "This language has neither a frequency list nor a known " +
            "alphabet.";
        submitButton.disabled = true;
        return;
    }

    function currentLearningType() {
        return form.querySelector(".learning-type:checked").value;
    }

    function refreshForLearningType() {
        const isWord = currentLearningType() === "word";
        wordFields.hidden = !isWord;
        targets.required = isWord;
        frequencyListSelect.required = isWord;
        if (isWord) {
            fillFrequencyListSelect(
                frequencyListSelect,
                frequencyLists,
                course.language,
            );
            fillLearningLexiconSelect(lexiconSelect, lexicons, course.language);
            fillLearningLexiconSelect(
                askLexiconSelect,
                lexicons,
                course.language,
            );
        }
    }

    for (const input of learningTypeInputs) {
        input.addEventListener("change", refreshForLearningType);
    }
    refreshForLearningType();

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const isWord = currentLearningType() === "word";

        const questionTypesChecked = checkedQuestionTypes(
            questionTypesContainer,
        );
        if (questionTypesChecked.length === 0) {
            createStatus.textContent = "Pick at least one question type.";
            return;
        }

        const body = {
            learning_type: currentLearningType(),
            name: nameInput.value.trim() || null,
            max_for_day: Number(maxForDayInput.value),
            play_audio: playAudioInput.checked,
            question_types: questionTypesChecked,
        };

        if (isWord) {
            const translationLanguages = Array.from(
                targets.selectedOptions,
                (option) => option.value,
            );
            if (translationLanguages.length === 0) {
                createStatus.textContent =
                    "Pick at least one language to translate into.";
                return;
            }
            body.translation_languages = translationLanguages;
            body.frequency_list = decodeFrequencyListValue(
                frequencyListSelect.value,
            );
            body.lexicon_id = lexiconSelect.value || null;
            body.ask_lexicon_id = askLexiconSelect.value || null;
        }

        createStatus.textContent = "Creating…";
        const result = await api(
            `/me/courses/${encodeURIComponent(courseId)}/learnings`,
            { method: "POST", body },
        );
        if (result.ok) {
            const { learning_id } = await result.json();
            location.href = `learn?learning=${encodeURIComponent(
                learning_id,
            )}`;
        } else {
            const { detail } = await result.json().catch(() => ({}));
            createStatus.textContent = detail || "Could not create learning.";
        }
    });
}

// Lexicon list page.

async function initLexicons() {
    requireAuth();

    const status = document.getElementById("status");
    const table = document.getElementById("lexicon-table");
    const rows = document.getElementById("lexicon-rows");
    const response = await api("/me/lexicons");
    const lexicons = await response.json();

    if (lexicons.length === 0) {
        status.textContent = "No lexicons yet.";
    } else {
        status.textContent = "";
        table.hidden = false;
    }
    for (const lexicon of lexicons) {
        const row = document.createElement("tr");

        const idCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = `lexicon?lexicon=${encodeURIComponent(
            lexicon.lexicon_id,
        )}`;
        // A leading star marks the main lexicon for its language.
        if (lexicon.is_main) link.append("★ ");
        if (lexicon.name) {
            link.append(lexicon.name);
            link.title = lexicon.lexicon_id;
        } else {
            link.append(identifierSpan(lexicon.lexicon_id));
        }
        idCell.appendChild(link);
        row.appendChild(idCell);

        const languageCell = document.createElement("td");
        languageCell.textContent = languageName(lexicon.language);
        row.appendChild(languageCell);

        const selectionCell = document.createElement("td");
        selectionCell.className = "strategy-text";
        selectionCell.textContent = lexicon.selection
            ? strategyIconPrefix(lexicon.selection) + lexicon.selection
            : "";
        row.appendChild(selectionCell);

        for (const value of [
            formatRate(lexicon.rate, lexicon.sd, 2),
            lexicon.words,
        ]) {
            const cell = document.createElement("td");
            cell.textContent = value;
            cell.style.textAlign = "right";
            row.appendChild(cell);
        }

        rows.appendChild(row);
    }
}

// Lexicon detail page.

async function initLexicon() {
    requireAuth();

    const lexiconId = new URLSearchParams(location.search).get("lexicon");
    document
        .getElementById("lexicon-heading")
        .replaceChildren("Lexicon: ", identifierSpan(lexiconId));

    const status = document.getElementById("status");
    const stats = document.getElementById("stats");
    const response = await api(
        `/me/lexicons/${encodeURIComponent(lexiconId)}/stats`,
    );
    if (!response.ok) {
        status.textContent = "Could not load statistics.";
        return;
    }
    const s = await response.json();
    status.textContent = "";

    // "Check this lexicon": available unless the precision goal was just met
    // and rechecking is still paused (see `check_available`).
    const checkLink = document.getElementById("check-link");
    if (s.check_available) {
        checkLink.href = `check?lexicon=${encodeURIComponent(lexiconId)}`;
    } else {
        checkLink.removeAttribute("href");
        checkLink.textContent = s.recheck_available_at
            ? `Check available in ${formatCountdown(
                  new Date(s.recheck_available_at).getTime() - Date.now(),
              )}`
            : "Check this lexicon";
    }

    // "Main" toggle: this lexicon's rate counts as the language's level.
    // Setting it replaces any other main lexicon for the same language.
    const toggle = document.getElementById("main-toggle");
    const language = languageName(s.language);
    function renderToggle(isMain) {
        toggle.textContent = isMain
            ? `★ Main for ${language} (click to unset)`
            : `Set as main for ${language}`;
        toggle.hidden = false;
    }
    renderToggle(s.is_main);
    toggle.addEventListener("click", async () => {
        const isMain = toggle.textContent.startsWith("★");
        const r = await api(`/me/lexicons/${encodeURIComponent(lexiconId)}/main`, {
            method: isMain ? "DELETE" : "PUT",
        });
        if (r.ok) renderToggle(!isMain);
    });

    const rows = [
        ["Language", language],
        [
            "Selection",
            s.selection ? strategyIconPrefix(s.selection) + s.selection : "—",
            "strategy-text",
        ],
        ["Frequency list", s.frequency_list_name ?? "—"],
        ["Words checked", s.words],
        ["Known", s.known],
        ["Don't know", s.dont_know],
        [
            "Vocabulary rate",
            s.rate === null
                ? "not enough data"
                : formatRate(s.rate, s.sd, 2),
        ],
        [
            "Precision goal (last 3 months)",
            s.achieved ? "Achieved" : "Not yet achieved",
        ],
    ];
    if (!s.check_available && s.recheck_available_at) {
        rows.push([
            "Next check available",
            formatCountdown(
                new Date(s.recheck_available_at).getTime() - Date.now(),
            ),
        ]);
    }
    renderDefinitionList(stats, rows);

    await setupLexiconSettings(lexiconId);

    // Delete: removes the lexicon and all its history, then returns to the list.
    const danger = document.getElementById("danger");
    const deleteStatus = document.getElementById("delete-status");
    danger.hidden = false;
    document
        .getElementById("delete-lexicon")
        .addEventListener("click", async () => {
            if (
                !confirm(
                    `Delete lexicon "${lexiconId}" and all its history? This ` +
                        "cannot be undone.",
                )
            ) {
                return;
            }
            deleteStatus.textContent = "Deleting…";
            const result = await api(
                `/me/lexicons/${encodeURIComponent(lexiconId)}`,
                { method: "DELETE" },
            );
            if (result.ok) {
                location.href = "lexicons";
            } else {
                deleteStatus.textContent = "Could not delete lexicon.";
            }
        });
}

// Fill and wire the lexicon settings form: display name, identifier (renaming
// moves the lexicon's URL, so the page redirects after a rename), and
// translation targets (which regenerate the dictionary/sentence config on
// save — also backfilling lexicons created before targets were
// auto-configured). The lexicon's identity (language, selection, frequency
// list) is immutable and not shown here. Pre-filled from the lexicon's
// current settings.
async function setupLexiconSettings(lexiconId) {
    const base = `/me/lexicons/${encodeURIComponent(lexiconId)}`;
    const section = document.getElementById("settings-section");
    const form = document.getElementById("settings-form");
    const nameInput = document.getElementById("setting-name");
    const idInput = document.getElementById("setting-id");
    const targets = document.getElementById("setting-targets");
    const settingsStatus = document.getElementById("settings-status");

    const [settingsResponse, targetResponse] = await Promise.all([
        api(`${base}/settings`),
        api("/translation-languages"),
    ]);
    if (!settingsResponse.ok) return;
    const settings = await settingsResponse.json();

    nameInput.value = settings.name || "";
    idInput.value = settings.lexicon_id;
    if (settings.name) {
        document.getElementById("lexicon-heading").textContent = settings.name;
    }
    fillLanguageSelect(
        targets,
        await targetResponse.json(),
        new Set(settings.translation_languages),
    );
    section.hidden = false;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const translationLanguages = Array.from(
            targets.selectedOptions,
            (option) => option.value,
        );
        if (translationLanguages.length === 0) {
            settingsStatus.textContent =
                "Pick at least one language to translate into.";
            return;
        }
        settingsStatus.textContent = "Saving…";
        const result = await api(`${base}/settings`, {
            method: "PATCH",
            body: {
                name: nameInput.value,
                lexicon_id: idInput.value,
                translation_languages: translationLanguages,
            },
        });
        if (result.ok) {
            const saved = await result.json();
            if (saved.lexicon_id !== lexiconId) {
                // The identifier is the page address: follow the rename.
                location.href = `lexicon?lexicon=${encodeURIComponent(
                    saved.lexicon_id,
                )}`;
                return;
            }
            const heading = document.getElementById("lexicon-heading");
            if (saved.name) {
                heading.textContent = saved.name;
            } else {
                heading.replaceChildren(
                    "Lexicon: ",
                    identifierSpan(saved.lexicon_id),
                );
            }
            settingsStatus.textContent = "Saved.";
        } else {
            const { detail } = await result.json().catch(() => ({}));
            settingsStatus.textContent = detail || "Could not save settings.";
        }
    });
}

// Convergence chart of the rate estimate (check page): an inline SVG in the
// footer seeded with the whole answer history from `/rate-trajectory` and
// grown live from the per-answer `/rate-estimate` values, so the reader sees
// the estimate stabilize as the session goes. Every color comes from CSS
// variables in `base.css`, so the chart follows the theme; the series color
// follows the estimator (`data-method` on the figure).
function createTrajectoryChart(figure, svg, tooltip) {
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

// Dashboard vocabulary-level history: one r line (plus ± SD band) per
// language, over calendar time. Same drawing approach as
// `createTrajectoryChart` (inline SVG, hover crosshair and tooltip), but
// there is no live session to grow it from — `setData` renders a fixed
// snapshot fetched once — and each language gets a color from a fixed chart
// palette (by position, cycling if there are more languages than colors)
// instead of sharing one CSS variable, since several lines share the chart.
// Deliberately not the language's own display color (`Language.color`,
// used elsewhere, e.g. `.language-code`): those aren't chosen as a set for
// mutual contrast, so two languages can end up close in hue. A legend below
// the chart spells out which line is which language.
const HISTORY_CHART_PALETTE = [
    "#2A78D6", // blue
    "#D6552A", // orange
    "#1BAF7A", // green
    "#B03ADB", // purple
    "#D6B22A", // gold
    "#2AAFD6", // cyan
    "#D62A6E", // rose
    "#6E8C2A", // olive
];

function createLanguageHistoryChart(figure, svg, tooltip, legend) {
    const SVG_NS = "http://www.w3.org/2000/svg";
    const MARGIN = { top: 10, right: 20, bottom: 20, left: 40 };

    let series = []; // [{ language, color, points: [{ date, rate, sd }] }].
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

    function tickLabel(value) {
        return Number.isInteger(value)
            ? value.toLocaleString("en-US")
            : String(Number(value.toFixed(2)));
    }

    function dateLabel(date) {
        return date.toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
        });
    }

    // The first of each month from `minDate` to `maxDate`, as timestamps.
    function monthStarts(minDate, maxDate) {
        const first = new Date(minDate);
        let cursor = new Date(first.getFullYear(), first.getMonth(), 1);
        if (cursor.getTime() < minDate) {
            cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
        }
        const ticks = [];
        while (cursor.getTime() <= maxDate) {
            ticks.push(cursor.getTime());
            cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
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

        // Horizontal hairline gridlines with their rate labels, one per
        // integer between the axis floor and ceiling.
        for (let value = yMin; value <= yMax; value += 1) {
            const line = y(value);
            parts.push(
                `<line class="grid" x1="${plot.left}" y1="${line}"` +
                    ` x2="${plot.right}" y2="${line}"/>`,
                `<text class="tick-label" x="${plot.left - 6}" y="${line}"` +
                    ` text-anchor="end" dominant-baseline="middle">` +
                    `${tickLabel(value)}</text>`,
            );
        }

        // The baseline and date ticks along it: one per month by default (a
        // history worth charting usually spans several), falling back to a
        // few evenly spaced day ticks when the whole range is under a month
        // and so has one month-start tick or none.
        parts.push(
            `<line class="grid" x1="${plot.left}" y1="${plot.bottom}"` +
                ` x2="${plot.right}" y2="${plot.bottom}"/>`,
        );
        const months = monthStarts(minDate, maxDate);
        if (months.length >= 2) {
            let previousYear = null;
            for (const t of months) {
                const date = new Date(t);
                const options =
                    date.getFullYear() === previousYear
                        ? { month: "short" }
                        : { month: "short", year: "numeric" };
                previousYear = date.getFullYear();
                parts.push(
                    `<text class="tick-label" x="${x(t)}"` +
                        ` y="${height - 4}" text-anchor="middle">` +
                        `${date.toLocaleDateString(undefined, options)}</text>`,
                );
            }
        } else {
            const dateSteps = 4;
            for (let step = 0; step <= dateSteps; step += 1) {
                const t = minDate + (step / dateSteps) * (maxDate - minDate);
                parts.push(
                    `<text class="tick-label" x="${x(t)}"` +
                        ` y="${height - 4}" text-anchor="middle">` +
                        `${dateLabel(new Date(t))}</text>`,
                );
            }
        }

        // One r line with its ± SD band per language, each in its own color.
        for (const one of known) {
            const upper = one.points
                .map((p) => `${x(p.date.getTime())},${y(p.rate + (p.sd || 0))}`)
                .join(" L ");
            const lower = one.points
                .slice()
                .reverse()
                .map((p) => `${x(p.date.getTime())},${y(p.rate - (p.sd || 0))}`)
                .join(" L ");
            parts.push(
                `<path class="band" d="M ${upper} L ${lower} Z"` +
                    ` fill="${one.color}"/>`,
                `<path class="line" d="M ${one.points
                    .map((p) => `${x(p.date.getTime())},${y(p.rate)}`)
                    .join(" L ")}" stroke="${one.color}"/>`,
            );
        }

        svg.innerHTML = parts.join("");
        svg.append(crosshair, focusDot);
        hideHover();
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
        const cx = scale.x(nearest.date.getTime());
        const cy = scale.y(nearest.rate);
        crosshair.setAttribute("x1", cx);
        crosshair.setAttribute("x2", cx);
        crosshair.setAttribute("y1", scale.plot.top);
        crosshair.setAttribute("y2", scale.plot.bottom);
        crosshair.style.visibility = "visible";
        focusDot.setAttribute("cx", cx);
        focusDot.setAttribute("cy", cy);
        focusDot.setAttribute("fill", nearestSeries.color);
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
        // Seed (and only ever seed) the chart with every language's history,
        // fetched once on page load.
        setData(histories) {
            series = histories.map((entry, index) => ({
                language: entry.language,
                color:
                    HISTORY_CHART_PALETTE[
                        index % HISTORY_CHART_PALETTE.length
                    ],
                points: entry.points.map((point) => ({
                    date: new Date(point.date),
                    rate: point.rate,
                    sd: point.sd,
                })),
            }));
            legend.replaceChildren();
            for (const one of series) {
                if (one.points.length < 2) continue;
                const item = document.createElement("span");
                const swatch = document.createElement("span");
                swatch.className = "swatch";
                swatch.style.backgroundColor = one.color;
                item.append(swatch, languageName(one.language));
                legend.append(item);
            }
            render();
        },
    };
}

// Stratum wheel (check page, stratified strategy only): eleven concentric
// circles fence ten annular bands, one per frequency stratum — the innermost
// band holds the most frequent words. Each answered word is a dot scattered
// inside its stratum's band, filled for "know", hollow for "don't know", and
// a band's width is proportional to how many dots it holds, so the wheel
// reads as a density map. The CSS transitions on rotation, `cx` and `r`
// make dots and boundaries slide smoothly as answers arrive.
function createStrataChart(figure, svg) {
    const SVG_NS = "http://www.w3.org/2000/svg";
    const CENTER = 150; // The viewBox is a fixed 300×300 square.
    const MIN_RADIUS = 40; // The innermost boundary; keeps the center open.
    const MAX_RADIUS = 140;
    const DOT_RADIUS = 3.5;
    const MIN_BAND = 4; // An empty stratum's band never quite vanishes.

    let nStrata = 0;
    let checkedAtSeed = 0; // Session answers already included in the seed.
    let seeded = false;
    const ringElements = []; // The band boundary circles, nStrata + 1.
    const rings = []; // Per stratum: [{ element, know, … }], insertion order.
    const phases = []; // Per stratum: where its first slot points, so the
    // bands' slot origins never line up into a radial streak.
    const pending = []; // Live answers arriving before the seed.

    // The band boundaries: every stratum gets the minimum band plus a
    // share of the remaining span proportional to its dot count.
    function boundaries() {
        const total = rings.reduce((sum, dots) => sum + dots.length, 0);
        const span = MAX_RADIUS - MIN_RADIUS - nStrata * MIN_BAND;
        const radii = [MIN_RADIUS];
        for (const dots of rings) {
            radii.push(
                radii[radii.length - 1] +
                    MIN_BAND +
                    (total ? (span * dots.length) / total : span / nStrata),
            );
        }
        return radii;
    }

    // Re-place everything: boundary circles at their radii, dots in evenly
    // spaced slots starting at the top, plus each dot's own stable jitter.
    // Both jitter components scale with the band's width (edges spared):
    // radially the dot scatters across the band, angularly it wanders by
    // the same distance in arc length — isotropic, so a thin band stays an
    // orderly ring while a wide band loosens into a point cloud. Updating
    // rotation and `cx` of dots already in the document triggers the slide
    // transitions.
    function layoutAll() {
        const radii = boundaries();
        for (const [index, ring] of ringElements.entries()) {
            ring.setAttribute("r", radii[index]);
        }
        for (const [stratum, dots] of rings.entries()) {
            const middle = (radii[stratum] + radii[stratum + 1]) / 2;
            const room = Math.max(
                radii[stratum + 1] - radii[stratum] - 2 * DOT_RADIUS - 2,
                0,
            );
            const slot = 360 / dots.length;
            for (const [index, dot] of dots.entries()) {
                dot.element.setAttribute(
                    "cx",
                    CENTER + middle + dot.drift * room * 2,
                );
                const arc =
                    ((dot.spin * room) / middle) * (180 / Math.PI);
                dot.element.style.transform =
                    `rotate(${phases[stratum] + index * slot + arc}deg)`;
            }
        }
    }

    // Create a dot (its jitter is drawn once and kept, so re-layouts never
    // make it wander) without adding it to the document: the caller runs
    // `layoutAll` first, so the dot pops up in place instead of sliding in.
    function place(stratum, know) {
        if (stratum == null || stratum < 0 || stratum >= nStrata) return null;
        const dot = document.createElementNS(SVG_NS, "circle");
        dot.setAttribute("class", `dot ${know ? "know" : "dont"}`);
        dot.setAttribute("cy", CENTER);
        dot.setAttribute("r", DOT_RADIUS);
        rings[stratum].push({
            element: dot,
            know,
            spin: Math.random() - 0.5,
            drift: Math.random() - 0.5,
        });
        return dot;
    }

    function add(stratum, know) {
        const dot = place(stratum, know);
        if (!dot) return;
        layoutAll();
        svg.append(dot);
    }

    // Remove the ring's most recent dot of that kind (for an undo).
    function remove(stratum, know) {
        if (stratum == null || stratum < 0 || stratum >= nStrata) return;
        const dots = rings[stratum];
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
        // Draw the rings and the whole history's dots, then replay the
        // answers this session recorded while the seed was loading (the
        // first `checkedNow` of them are already inside the seed).
        setSeed(answers, total, checkedNow) {
            nStrata = total;
            checkedAtSeed = checkedNow;
            rings.length = 0;
            ringElements.length = 0;
            phases.length = 0;
            svg.replaceChildren();
            // One boundary circle more than there are strata bands.
            for (let boundary = 0; boundary <= nStrata; boundary += 1) {
                const ring = document.createElementNS(SVG_NS, "circle");
                ring.setAttribute("class", "ring");
                ring.setAttribute("cx", CENTER);
                ring.setAttribute("cy", CENTER);
                svg.append(ring);
                ringElements.push(ring);
                if (boundary < nStrata) {
                    rings.push([]);
                    phases.push(Math.random() * 360);
                }
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

// Session pages: lexicon checking and learning repetition share one flow.
// Rather than fetch one word per answer, the client keeps a small queue of
// upcoming words (each with its translation already loading) plus a history
// stack, so answering is instant and any number of answers can be undone.
// `base` is the resource path, e.g. `/me/lexicons/fr`.

const BUFFER_SIZE = 3; // Words kept prefetched ahead of the current one.

async function runSession(base, doneText) {
    const word = document.getElementById("word");
    const status = document.getElementById("status");
    const answers = document.getElementById("answers");
    const translation = document.getElementById("translation");
    const undoBar = document.getElementById("undo-bar");
    const undoWord = document.getElementById("undo-word");
    const question = document.getElementById("question");
    const sentence = document.getElementById("sentence");

    const showButton = document.getElementById("show-translation");
    const showButtonLabel = document.getElementById("show-translation-label");
    const noTranslation = document.getElementById("no-translation");
    const externalLinks = document.getElementById("external-links");
    const googleLink = document.getElementById("google-link");
    const yandexLink = document.getElementById("yandex-link");
    const wiktionaryLink = document.getElementById("wiktionary-link");
    const kaikkiLink = document.getElementById("kaikki-link");

    const queue = []; // Upcoming { word, lastResponse, lastTime, results }.
    const history = []; // Answered { word } (most recent last), for undo.
    let refill = null; // The in-flight refill, so `/next` calls never overlap.
    let current = null; // The item on screen.
    let revealed = false; // Whether the current word's translation is shown.
    let language = null; // ISO code of the session's language (from `/next`).
    let answering = false; // Guards a second click landing before advance().

    // Live "r = 7.23 ± 0.14" estimate, computed server-side by the estimator
    // matching the lexicon's selection strategy and refreshed after every
    // answer. Fire-and-forget: a stale response (superseded by a later
    // request) is dropped, and the element is absent on non-check pages.
    const rateEstimate = document.getElementById("rate-estimate");
    let rateRequest = 0;

    // The estimate convergence chart (check page only; the figure is absent
    // elsewhere): seeded with the replayed history, grown per answer.
    const trajectoryFigure = document.getElementById("trajectory");
    const chart = trajectoryFigure
        ? createTrajectoryChart(
              trajectoryFigure,
              document.getElementById("trajectory-svg"),
              document.getElementById("trajectory-tooltip"),
          )
        : null;

    // The stratum wheel, drawn for stratified lexicons only (the trajectory
    // response carries no strata for the other strategies).
    const strataFigure = document.getElementById("strata");
    const strataChart = strataFigure
        ? createStrataChart(
              strataFigure,
              document.getElementById("strata-svg"),
          )
        : null;

    // Seed both charts with the whole history from one response. A lexicon
    // whose strategy has no estimator (or no frequency list) just keeps the
    // charts hidden.
    async function loadTrajectory() {
        if (!chart) return;
        const response = await api(`${base}/rate-trajectory`);
        if (!response.ok) return;
        const data = await response.json();
        chart.setSeed(data, counts.checked);
        if (strataChart && data.strata) {
            strataChart.setSeed(data.strata, data.n_strata, counts.checked);
        }
    }

    // Live session status (check page only; the elements are absent
    // elsewhere): how many words were answered this session, split into
    // know / don't know, plus the current word's strategy context — its
    // frequency rank and, for the stratified strategy, its stratum.
    const sessionCounts = document.getElementById("session-counts");
    const wordInfo = document.getElementById("word-info");
    const counts = { checked: 0, know: 0, dont: 0 };
    let selection = null; // The lexicon's selection strategy (from `/next`).
    let listSize = null; // Frequency list length (from `/next`).
    let strataCount = null; // Total strata for `stratified` (from `/next`).

    function renderSessionStatus() {
        if (sessionCounts) {
            sessionCounts.textContent =
                `Checked: ${counts.checked} · ` +
                `know: ${counts.know} · don't know: ${counts.dont}`;
            sessionCounts.hidden = false;
        }
        if (!wordInfo) return;
        if (!current || current.rank == null) {
            wordInfo.hidden = true;
            return;
        }
        const parts = [];
        if (selection) parts.push(selection);
        let place = `word #${current.rank.toLocaleString("en-US")}`;
        if (listSize) place += ` of ${listSize.toLocaleString("en-US")}`;
        parts.push(place);
        if (current.stratum != null && strataCount) {
            parts.push(`stratum ${current.stratum + 1}/${strataCount}`);
        }
        wordInfo.textContent = parts.join(" · ");
        wordInfo.hidden = false;
    }

    // Returns whether the trailing-window precision goal is met, so the
    // check loop can stop and hand the session back once it is.
    async function refreshRateEstimate() {
        if (!rateEstimate) return false;
        const token = ++rateRequest;
        // How many session answers this estimate covers, for the chart.
        const checked = counts.checked;
        const response = await api(`${base}/rate-estimate`);
        if (token !== rateRequest || !response.ok) return false;
        const estimate = await response.json();
        if (token !== rateRequest) return false;
        chart?.noteEstimate(checked, estimate.rate, estimate.sd);
        if (estimate.rate === null) {
            rateEstimate.hidden = true;
            return Boolean(estimate.achieved);
        }
        rateEstimate.textContent =
            `r = ${estimate.rate.toFixed(2)} ± ${estimate.sd.toFixed(2)}`;
        rateEstimate.title = `${estimate.method[0].toUpperCase()}${estimate.method.slice(1)} estimate`;
        rateEstimate.hidden = false;
        return Boolean(estimate.achieved);
    }

    // The lexicon/course's dictionaries, loaded once. Each is fetched
    // separately per word so a slow one (e.g. Google Translate over the
    // network) never holds up the fast ones; loaded on demand below.
    let dictionaries = [];

    // Start loading a word's translation now so it's ready when needed. Each
    // dictionary is fetched independently and its result stored by position in
    // `item.results` (`undefined` until it resolves, then a list of rendered
    // dictionary entries). As soon as the first one with content arrives the
    // reveal button is enabled; the rest fill in afterwards.
    function attachTranslation(item) {
        item.results = dictionaries.map(() => undefined);
        dictionaries.forEach(({ index }, slot) => {
            api(
                `${base}/translation?word=${encodeURIComponent(item.word)}` +
                    `&index=${index}`,
            )
                .then((response) => (response.ok ? response.json() : null))
                .then((data) => {
                    item.results[slot] = (data && data.dictionaries) || [];
                    onTranslationProgress(item);
                });
        });
    }

    // React to one of `item`'s dictionaries resolving: enable the reveal
    // button once any has content, or — if every dictionary resolved with
    // nothing — replace the button with a "No translation found." notice.
    // The translation itself renders regardless of `revealed` (blurred until
    // then via CSS). Ignored once the user has moved to another word.
    function onTranslationProgress(item) {
        if (current !== item) return;
        const results = item.results || [];
        const hasContent = results.some((result) => result && result.length);
        const allResolved = results.every((result) => result !== undefined);
        if (hasContent) {
            showButton.disabled = false;
        } else if (allResolved) {
            showButton.hidden = true;
            noTranslation.hidden = false;
        }
        renderTranslation(item);
    }

    // Render one block per dictionary entry into the translation area.
    function appendDictionaries(entries) {
        for (const entry of entries) {
            const block = document.createElement("div");
            block.className = "dictionary";

            const name = document.createElement("div");
            name.className = "dictionary-name";
            name.textContent = entry.dictionary;

            const body = document.createElement("div");
            body.className = "dictionary-body";
            // The server returns a safe HTML fragment (text escaped, fixed
            // tags).
            body.innerHTML = entry.html;

            block.append(name, body);
            translation.append(block);
        }
    }

    // Likewise the example sentence: a slow Tatoeba lookup, kept off `/next`
    // and prefetched so it appears under the word when ready (HTML or null).
    function attachSentence(item) {
        item.sentence = api(
            `${base}/sentence?word=${encodeURIComponent(item.word)}`,
        )
            .then((response) => (response.ok ? response.json() : null))
            .then((data) => (data ? data.sentence : null));
    }

    // Refill the queue, skipping the current word and anything already queued
    // so the server never hands back a duplicate. At most one refill runs at
    // a time: selection can be deterministic on the server, so two `/next`
    // requests racing over the same state would return the same words and
    // queue duplicates.
    function fill() {
        if (!refill) {
            refill = refillQueue().finally(() => {
                refill = null;
            });
        }
        return refill;
    }

    async function refillQueue() {
        const need = BUFFER_SIZE - queue.length;
        if (need <= 0) return;
        const params = new URLSearchParams({ count: String(need) });
        for (const item of [current, ...queue]) {
            if (item) params.append("exclude", item.word);
        }
        const response = await api(`${base}/next?${params}`);
        if (!response.ok) return;
        const batch = await response.json();
        language = batch.language;
        if (batch.selection) {
            selection = batch.selection;
            listSize = batch.list_size;
            strataCount = batch.strata;
        }
        for (const card of batch.words) {
            // A word already on screen, queued, or answered this session can
            // still come back from a `/next` that raced with an answer being
            // recorded; presenting it again would double-count it.
            if (
                (current && current.word === card.word) ||
                queue.some((item) => item.word === card.word) ||
                history.some((entry) => entry.word === card.word)
            ) {
                continue;
            }
            const item = {
                word: card.word,
                lastResponse: card.last_response,
                lastTime: card.last_time,
                rank: card.rank,
                stratum: card.stratum,
                results: null,
                sentence: null,
            };
            attachTranslation(item);
            attachSentence(item);
            queue.push(item);
        }
    }

    function render() {
        translation.replaceChildren();
        translation.classList.add("blurred");
        revealed = false;
        showButton.hidden = false;
        showButton.disabled = true;
        showButtonLabel.textContent = "Show translation";
        noTranslation.hidden = true;
        undoBar.hidden = history.length === 0;
        if (history.length) {
            undoWord.textContent = history[history.length - 1].word;
        }
        renderLastAnswer();
        renderSentence();
        renderExternalLinks();
        renderSessionStatus();
        word.classList.toggle(
            "top",
            Boolean(current) && current.rank != null && current.rank <= 10000,
        );
        if (current) {
            word.textContent = current.word;
            status.textContent = "";
            answers.hidden = false;
            // Enable the reveal button now if a dictionary already resolved
            // while this word was queued.
            onTranslationProgress(current);
        } else {
            word.textContent = "";
            answers.hidden = true;
            status.textContent = doneText;
        }
    }

    // Point the external lookup links at the current word: a Google search
    // (`translate French word "bonjour"`), a Yandex translation into English,
    // the word's English Wiktionary entry, and its Kaikki (Wiktionary data)
    // page. Hidden when no word is showing.
    function renderExternalLinks() {
        if (!current) {
            externalLinks.hidden = true;
            return;
        }
        const word = encodeURIComponent(current.word);
        const langName = languageName(language);
        const query = `Translate ${langName} word "${current.word}".`;
        googleLink.href =
            `https://www.google.com/search?q=${encodeURIComponent(query)}`;
        yandexLink.href =
            `https://translate.yandex.ru/?source_lang=${encodeURIComponent(language)}` +
            `&target_lang=en&text=${word}`;
        // Wiktionary anchors the per-language section by its English name.
        wiktionaryLink.href =
            `https://en.wiktionary.org/wiki/${word}` +
            `#${encodeURIComponent(langName.replace(/ /g, "_"))}`;
        // Kaikki stores each word under <Language>/meaning/<c1>/<c1c2>/<word>.
        const lower = current.word.toLowerCase();
        kaikkiLink.href =
            `https://kaikki.org/dictionary/${encodeURIComponent(langName)}/meaning/` +
            `${encodeURIComponent(lower.slice(0, 1))}/` +
            `${encodeURIComponent(lower.slice(0, 2))}/` +
            `${encodeURIComponent(lower)}.html`;
        externalLinks.hidden = false;
    }

    // Show the current word's example sentence: "Loading…" until its prefetch
    // resolves, then the sentence or "No sentence." Results are ignored if we
    // have since moved to another word.
    function renderSentence() {
        // Keep the sentence box present (fixed height in CSS) so the layout
        // never jumps; fill it with dots, the sentence, or a dash.
        sentence.hidden = false;
        if (!current || !current.sentence) {
            sentence.replaceChildren();
            return;
        }
        sentence.replaceChildren(loadingDots());
        const item = current;
        // The server returns a safe HTML fragment (text escaped, word in <b>).
        item.sentence.then((html) => {
            if (current !== item) return;
            if (html) {
                sentence.innerHTML = html;
            } else {
                sentence.textContent = "—";
            }
        });
    }

    // Show what the user last answered for the current word, and when.
    function renderLastAnswer() {
        if (current && current.lastResponse) {
            const when = current.lastTime
                ? ` (${relativeTime(current.lastTime)})`
                : "";
            question.textContent =
                `Do you know at least one meaning of the word? Last answer was ${current.lastResponse}${when}.`;
        } else {
            question.textContent =
                `Do you know at least one meaning of the word?`;
        }
    }

    // Show the "next word is loading" placeholder everywhere the previous
    // word's content lingers: the word itself, its translation, and its
    // sentence. Used whenever the next word isn't ready to show yet, so
    // nothing stale is left behind — e.g. an old translation still visible
    // while the word slot has already moved on (or vice versa), which reads
    // as "did my answer actually not go through?".
    function showLoadingPlaceholder() {
        word.replaceChildren(loadingDots());
        translation.classList.remove("blurred");
        translation.replaceChildren(loadingDots());
        sentence.replaceChildren(loadingDots());
    }

    // Move to the next queued word, topping the queue back up in the
    // background so the wait is hidden behind the user's reading time.
    async function advance() {
        if (queue.length === 0) {
            // No word prefetched yet (first load, or the buffer ran dry):
            // show the placeholder while `/next` is in flight.
            showLoadingPlaceholder();
            status.textContent = "";
            await fill();
            // The awaited refill may have started before the last answer was
            // recorded and had all its words dropped as duplicates; one more
            // round trip reads the settled state.
            if (queue.length === 0) await fill();
        }
        current = queue.shift() || null;
        render();
        void fill();
    }

    async function answer(response, toSkip = false) {
        if (!current || answering) return;
        answering = true;
        const answered = current.word;
        // Hide already answered word, translation, and sentence.
        showLoadingPlaceholder();
        // Remember the response and strategy context so an undo can both
        // rewind the session counters and re-present the word annotated.
        history.push({
            word: answered,
            response,
            rank: current.rank,
            stratum: current.stratum,
        });
        counts.checked += 1;
        if (response === "know") counts.know += 1;
        else if (response === "dont") counts.dont += 1;
        if (response === "know" || response === "dont") {
            strataChart?.noteAnswer(
                counts.checked,
                current.stratum,
                response === "know",
            );
        }
        try {
            await api(`${base}/answer`, {
                method: "POST",
                body: { word: answered, response, to_skip: toSkip },
            });
            if (await refreshRateEstimate()) {
                // The trailing-window precision goal is met: the checking
                // process is done, so hand the session back automatically.
                status.textContent = "Goal reached — nice work!";
                location.href = "lexicons";
                return;
            }
            await advance();
        } finally {
            answering = false;
        }
    }

    // Remove the most recent answer and re-present that word to re-answer it.
    // Repeating walks back through the history stack.
    async function undo() {
        if (history.length === 0) return;
        const response = await api(`${base}/undo`, { method: "POST" });
        if (!response.ok) return;
        const { word: undone } = await response.json();
        if (!undone) return;
        const entry = history.pop();
        counts.checked -= 1;
        if (entry.response === "know") counts.know -= 1;
        else if (entry.response === "dont") counts.dont -= 1;
        chart?.noteUndo(counts.checked);
        if (entry.response === "know" || entry.response === "dont") {
            strataChart?.noteUndo(
                counts.checked,
                entry.stratum,
                entry.response === "know",
            );
        }
        if (current) queue.unshift(current);
        current = {
            word: undone,
            rank: entry.rank,
            stratum: entry.stratum,
            results: null,
            sentence: null,
        };
        attachTranslation(current);
        attachSentence(current);
        void refreshRateEstimate();
        render();
    }

    // Toggle the current word's translation between blurred and revealed;
    // the content itself is already rendered (see `renderTranslation`/
    // `render`), so this only flips the blur and the button's label — the
    // button stays put so the same key/click hides it again.
    function toggleTranslation() {
        if (!current) return;
        revealed = !revealed;
        translation.classList.toggle("blurred", !revealed);
        showButtonLabel.textContent = revealed
            ? "Hide translation"
            : "Show translation";
    }

    // Render every dictionary that has resolved so far for `item`, in
    // configured order (so a fast dictionary that resolves later still keeps
    // its place). Shows "Loading…" until the first arrives and "No
    // translation found." once every dictionary has resolved empty. Runs
    // whether or not the translation is revealed — blur (removed by
    // `showTranslation`) is what actually hides it from the user.
    function renderTranslation(item) {
        if (current !== item) return;
        translation.replaceChildren();
        const results = item.results || [];
        const groups = [];
        for (const result of results) {
            if (result) groups.push(...result);
        }
        if (groups.length) {
            appendDictionaries(groups);
        } else if (results.every((result) => result !== undefined)) {
            translation.textContent = "No translation found.";
        } else {
            translation.replaceChildren(loadingDots());
        }
    }

    for (const button of answers.querySelectorAll("button")) {
        button.addEventListener("click", () =>
            answer(button.dataset.response, button.dataset.skip === "true"),
        );
    }
    document
        .getElementById("show-translation")
        .addEventListener("click", toggleTranslation);
    document.getElementById("undo").addEventListener("click", undo);

    // Keyboard shortcuts: each button's `data-key` triggers a click (matches
    // the CLI), plus space to toggle the translation.
    function shortcutButton(event) {
        if (event.ctrlKey || event.metaKey || event.altKey) return null;
        if (event.target.matches("input, textarea, select")) return null;
        const key = event.key === " " ? " " : event.key.toLowerCase();
        const button = document.querySelector(`button[data-key="${key}"]`);
        // Skip a hidden button (e.g. the reveal button once it has been
        // replaced by the "No translation found." notice).
        return button && !button.hidden ? button : null;
    }
    // Act on key *release*, not press: a held key auto-repeats keydown, which
    // would rifle one answer (e.g. "yes") through every buffered word. keydown
    // only suppresses the key's default and arms the key; keyup fires the click
    // once, so each answer needs a deliberate press and release.
    const armedKeys = new Set();
    document.addEventListener("keydown", (event) => {
        if (!shortcutButton(event)) return;
        event.preventDefault();
        armedKeys.add(event.code);
    });
    document.addEventListener("keyup", (event) => {
        if (!armedKeys.delete(event.code)) return;
        const button = shortcutButton(event);
        if (!button) return;
        event.preventDefault();
        // Briefly flash the pressed state so a keyboard shortcut gives the same
        // visual feedback as a mouse click (a programmatic click does not
        // trigger :active).
        button.classList.add("pressed");
        setTimeout(() => button.classList.remove("pressed"), 120);
        button.click();
    });

    word.replaceChildren(loadingDots());
    if (await refreshRateEstimate()) {
        // Reached directly (e.g. a stale link) while the goal is already
        // met: nothing to check, so hand the session back right away.
        status.textContent = "Goal reached — nice work!";
        location.href = "lexicons";
        return;
    }
    void loadTrajectory();
    // Load the dictionary list first so the per-word prefetch knows which
    // dictionaries to request; an empty list just means no translations.
    const dictionariesResponse = await api(`${base}/dictionaries`);
    if (dictionariesResponse.ok) {
        dictionaries = await dictionariesResponse.json();
    }
    await advance();
}

// Learning session (production recall): the word is blanked and the user types
// it, auto-accepted the instant the entry matches the card's `accepted` forms.
// Due repetitions come first (`/next`); then new words (`/new`), which may first
// run a know/don't-know lexicon check (`check_lexicon`) before being taught.

async function runLearnSession(base) {
    const status = document.getElementById("status");
    const undoBar = document.getElementById("undo-bar");
    const undoWord = document.getElementById("undo-word");

    // Type-the-word box.
    const teachBox = document.getElementById("teach-box");
    const wordEl = document.getElementById("word");
    const input = document.getElementById("answer-input");
    const symbolButtons = document.getElementById("symbol-buttons");
    const answers = document.getElementById("answers");
    const question = document.getElementById("question");
    const translation = document.getElementById("translation");
    const sentence = document.getElementById("sentence");
    const sentenceTranslation = document.getElementById("sentence-translation");
    const externalLinks = document.getElementById("external-links");
    const googleLink = document.getElementById("google-link");
    const yandexLink = document.getElementById("yandex-link");
    const wiktionaryLink = document.getElementById("wiktionary-link");
    const kaikkiLink = document.getElementById("kaikki-link");
    const continueBar = document.getElementById("continue-bar");
    const continueButton = document.getElementById("continue");
    const cardStatus = document.getElementById("card-status");

    // Know box.
    const knowBox = document.getElementById("know-box");
    const knowHeading = document.getElementById("know-heading");
    const knowWord = document.getElementById("know-word");
    const knowShowBar = document.getElementById("know-show-bar");
    const knowShow = document.getElementById("know-show");
    const knowShowLabel = document.getElementById("know-show-label");
    const knowAnswers = document.getElementById("know-answers");
    const knowMeaning = document.getElementById("know-meaning");
    const knowContinueBar = document.getElementById("know-continue-bar");
    const knowContinue = document.getElementById("know-continue");

    // Choice box.
    const choiceBox = document.getElementById("choice-box");
    const choiceWord = document.getElementById("choice-word");
    const choiceOptions = document.getElementById("choice-options");
    const choiceContinueBar = document.getElementById("choice-continue-bar");
    const choiceContinue = document.getElementById("choice-continue");

    // Connect box.
    const connectBox = document.getElementById("connect-box");
    const connectWords = document.getElementById("connect-words");
    const connectTranslations = document.getElementById("connect-translations");
    const connectContinueBar = document.getElementById("connect-continue-bar");
    const connectContinue = document.getElementById("connect-continue");

    // Ask box (new-word lexicon check).
    const askBox = document.getElementById("ask-box");
    const askWord = document.getElementById("ask-word");

    const history = []; // Answered words (most recent last), for undo.
    const handledNew = new Set(); // New words decided this session.
    let current = null; // The current question/item (carries a `type`).
    let answeredWrong = false; // type_word: word revealed after "I don't know".
    let presentedAt = 0; // When the current card was shown (for `request_time`).
    let language = null;
    let dictionaries = [];
    let newExhausted = false; // `/new` has nothing more to offer.
    let playAudio = true; // Learning setting: play pronunciation audio.

    // Show exactly one question box and hide the rest.
    function showBox(name) {
        teachBox.hidden = name !== "type";
        knowBox.hidden = name !== "know";
        choiceBox.hidden = name !== "choice";
        connectBox.hidden = name !== "connect";
        askBox.hidden = name !== "ask";
    }

    // Render dictionary entries (safe HTML fragments) into a container.
    function appendDictionaries(container, entries) {
        for (const entry of entries) {
            const block = document.createElement("div");
            block.className = "dictionary";
            const name = document.createElement("div");
            name.className = "dictionary-name";
            name.textContent = entry.dictionary;
            const body = document.createElement("div");
            body.className = "dictionary-body";
            body.innerHTML = entry.html; // Safe HTML fragment from the server.
            block.append(name, body);
            container.append(block);
        }
    }

    // Prefetch a word's meaning (word blanked by the server) for type_word;
    // each dictionary resolves independently so a slow one never blocks.
    function attachTranslation(item) {
        item.results = dictionaries.map(() => undefined);
        dictionaries.forEach(({ index }, slot) => {
            api(
                `${base}/translation?word=${encodeURIComponent(item.word)}` +
                    `&index=${index}`,
            )
                .then((response) => (response.ok ? response.json() : null))
                .then((data) => {
                    item.results[slot] = (data && data.dictionaries) || [];
                    if (current === item) renderMeaning(item);
                });
        });
    }
    function renderMeaning(item) {
        if (current !== item) return;
        translation.replaceChildren();
        const results = item.results || [];
        const groups = [];
        for (const result of results) if (result) groups.push(...result);
        if (groups.length) {
            appendDictionaries(translation, groups);
        } else if (results.every((result) => result !== undefined)) {
            translation.textContent = "No translation found.";
        } else {
            translation.textContent = "Loading…";
        }
    }
    // The course `/sentence` blanks the target word and pairs the example with
    // one of its translations, both shown as the recall prompt. The example's
    // id is remembered so it can be recorded as provenance with the answer.
    function attachSentence(item) {
        item.sentenceId = null;
        item.sentence = api(
            `${base}/sentence?word=${encodeURIComponent(item.word)}`,
        )
            .then((response) => (response.ok ? response.json() : null))
            .then((data) => {
                if (data && data.sentence) {
                    item.sentenceId = data.sentence_id ?? null;
                    return { html: data.sentence, translation: data.translation };
                }
                return null;
            });
    }
    // Play a word's pronunciation from the course's audio providers. The audio
    // endpoint needs the bearer token, so it's fetched as a blob through `api`
    // (an <audio src> can't send the header) and played from an object URL.
    // Best-effort: missing audio (404) or an autoplay refusal is ignored, and
    // the previous URL is revoked so blobs don't leak.
    let audioUrl = null;
    async function playWordAudio(word) {
        if (!playAudio) return;
        const response = await api(
            `${base}/audio?word=${encodeURIComponent(word)}`,
        );
        if (!response.ok) return;
        const blob = await response.blob();
        if (audioUrl) URL.revokeObjectURL(audioUrl);
        audioUrl = URL.createObjectURL(blob);
        new Audio(audioUrl).play().catch(() => {});
    }

    // Build a type_word item (the typed-recall card), kicking off its meaning
    // and example prefetch.
    function makeItem(card) {
        const item = {
            type: "type_word",
            word: card.word,
            accepted: card.accepted || [card.word],
            source: card.source || "review",
            checkLexicon: card.checkLexicon || null,
            results: null,
            sentence: null,
        };
        attachTranslation(item);
        attachSentence(item);
        return item;
    }

    // Get the next due review question from the server, which chooses its type
    // (type_word / know / choice / connect). `null` when nothing is due.
    async function fetchQuestion() {
        const response = await api(`${base}/question`);
        if (!response.ok) return null;
        const data = await response.json();
        if (data.language) language = data.language;
        return data.type ? data : null;
    }

    // Get one new word to add from `/new` (or null when none remains), skipping
    // words already decided this session.
    async function fetchNew() {
        if (newExhausted) return null;
        const params = new URLSearchParams();
        for (const word of handledNew) params.append("exclude", word);
        const response = await api(`${base}/new?${params}`);
        if (!response.ok) return null;
        const data = await response.json();
        if (!data.word) {
            newExhausted = true;
            return null;
        }
        // First exposure of a word learned directly is a `know` card when the
        // server allows it: a never-seen word cannot be typed from its
        // meaning. After an `ask_lexicon` check the know/don't-know question
        // was already asked, so teaching by typing follows instead.
        if (!data.check_lexicon && data.question_type === "know") {
            return { type: "know", word: data.word, source: "new" };
        }
        return makeItem({
            word: data.word,
            accepted: data.accepted,
            source: "new",
            checkLexicon: data.check_lexicon,
        });
    }

    // Present a server-chosen review question by its type.
    // Show the current word's streak and when it was last answered (as the
    // lexicon check page does). Empty for connect cards (several words at
    // once) and for new words.
    function renderCardStatus(q) {
        if (!q || q.streak == null) {
            cardStatus.textContent = "";
            return;
        }
        const when = q.last_answer_time
            ? ` · last answered ${relativeTime(q.last_answer_time)}`
            : "";
        cardStatus.textContent = `Streak: ${q.streak}${when}`;
    }

    function presentReview(q) {
        renderCardStatus(q);
        if (q.type === "type_word") {
            current = makeItem({ word: q.words[0], accepted: q.accepted });
            renderTeach();
        } else if (q.type === "know") {
            current = { type: "know", word: q.words[0] };
            renderKnow();
        } else if (q.type === "choice") {
            current = {
                type: "choice",
                word: q.words[0],
                options: q.options,
                answer: q.answer,
            };
            renderChoice();
        } else if (q.type === "connect") {
            current = { type: "connect", pairs: q.pairs };
            renderConnect();
        }
    }

    // Pick the next thing to present: a due review question first (its type
    // chosen by the server), then a new word (a `know` card when the server
    // allows it, or taught as type_word after a know/don't-know lexicon
    // check).
    async function advance() {
        answeredWrong = false;
        status.textContent = "Loading…";
        const q = await fetchQuestion();
        status.textContent = "";
        if (q) {
            presentReview(q);
            return;
        }
        const item = await fetchNew();
        if (item) {
            // A new word has no streak or last answer to show.
            cardStatus.textContent = "New word — never answered yet.";
            current = item;
            if (item.checkLexicon) renderAsk();
            else if (item.type === "know") renderKnow();
            else renderTeach();
            return;
        }
        current = null;
        renderCardStatus(null);
        renderDone();
    }

    // Teaching: show the meaning (word blanked) and a translated example as the
    // prompt, blank the word's answer slot, and await typing.
    function renderTeach() {
        showBox("type");
        answeredWrong = false;
        continueBar.hidden = true;
        answers.hidden = false;
        input.hidden = false;
        input.value = "";
        input.disabled = false;
        undoBar.hidden = history.length === 0;
        if (history.length) {
            undoWord.textContent = history[history.length - 1].word;
        }
        wordEl.textContent = "_".repeat([...current.word].length);
        question.textContent =
            current.source === "new" ? "New word — type it." : "Type the word.";
        status.textContent = "";
        presentedAt = Date.now();
        renderMeaning(current);
        renderSentence();
        renderExternalLinks();
        input.focus();
    }

    // New-word check: ask whether the user already knows it (recorded in the
    // course's `ask_lexicon`).
    function renderAsk() {
        showBox("ask");
        askWord.textContent = current.word;
        status.textContent = "";
        undoBar.hidden = history.length === 0;
    }

    function renderDone() {
        showBox("type");
        input.hidden = true;
        answers.hidden = true;
        continueBar.hidden = true;
        wordEl.textContent = "";
        sentence.hidden = true;
        sentenceTranslation.hidden = true;
        question.textContent = "";
        externalLinks.hidden = true;
        translation.replaceChildren();
        status.textContent = "Nothing to learn right now.";
        undoBar.hidden = history.length === 0;
    }

    // Know: see the word, self-assess Know/Don't-know; either way the full
    // meaning is shown throughout, blurred until "Show translation" is
    // pressed or the word is self-assessed.
    function renderKnow() {
        showBox("know");
        status.textContent = "";
        undoBar.hidden = history.length === 0;
        if (history.length) {
            undoWord.textContent = history[history.length - 1].word;
        }
        knowHeading.textContent =
            current.source === "new"
                ? "New word — do you know it?"
                : "Do you know this word?";
        knowWord.textContent = current.word;
        knowShowBar.hidden = false;
        knowShowLabel.textContent = "Show translation";
        knowAnswers.hidden = false;
        knowMeaning.hidden = false;
        knowMeaning.classList.add("blurred");
        knowMeaning.replaceChildren(loadingDots());
        knowContinueBar.hidden = true;
        current.pendingResponse = null;
        presentedAt = Date.now();
        void loadKnowMeaning(current);
    }
    // Fetch the card's full meaning (word shown) into the (blurred) meaning
    // area, so it is ready the instant it needs to be legible.
    async function loadKnowMeaning(item) {
        const groups = [];
        await Promise.all(
            dictionaries.map(async ({ index }) => {
                const response = await api(
                    `${base}/translation?word=${encodeURIComponent(item.word)}` +
                        `&index=${index}&hide_word=false`,
                );
                if (response.ok) {
                    const data = await response.json();
                    if (data.dictionaries) groups.push(...data.dictionaries);
                }
            }),
        );
        if (current !== item) return;
        knowMeaning.replaceChildren();
        if (groups.length) appendDictionaries(knowMeaning, groups);
        else knowMeaning.textContent = "No translation found.";
    }
    // Peek at the translation before self-assessing (as on the lexicon check
    // page): toggles the blur, records nothing, the Know/Don't-know buttons
    // stay. The button itself stays put so the same key/click hides it again.
    function knowShowTranslation() {
        if (!current || current.type !== "know" || current.pendingResponse) {
            return;
        }
        const stillBlurred = knowMeaning.classList.toggle("blurred");
        knowShowLabel.textContent = stillBlurred
            ? "Show translation"
            : "Hide translation";
    }
    async function knowSelfAssess(knows) {
        if (!current || current.type !== "know" || current.pendingResponse) {
            return;
        }
        current.pendingResponse = knows ? "y" : "n";
        knowAnswers.hidden = true;
        knowShowBar.hidden = true;
        knowMeaning.classList.remove("blurred");
        await postAnswer(current.word, current.pendingResponse);
        const item = current;
        if (current !== item) return;
        knowContinueBar.hidden = false;
        knowContinue.focus();
        void playWordAudio(item.word);
    }

    // Choice: pick the right translation among several.
    function renderChoice() {
        showBox("choice");
        status.textContent = "";
        undoBar.hidden = history.length === 0;
        if (history.length) {
            undoWord.textContent = history[history.length - 1].word;
        }
        choiceWord.textContent = current.word;
        choiceContinueBar.hidden = true;
        choiceOptions.replaceChildren();
        current.answered = false;
        current.options.forEach((option, index) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "option";
            button.dataset.key = String(index + 1);
            button.textContent = option;
            button.addEventListener("click", () => chooseOption(option));
            choiceOptions.append(button);
        });
        presentedAt = Date.now();
    }
    async function chooseOption(option) {
        if (!current || current.type !== "choice" || current.answered) return;
        current.answered = true;
        for (const button of choiceOptions.querySelectorAll("button")) {
            button.disabled = true;
            if (button.textContent === current.answer) {
                button.classList.add("correct");
            } else if (button.textContent === option) {
                button.classList.add("wrong");
            }
        }
        await postAnswer(current.word, option === current.answer ? "y" : "n");
        choiceContinueBar.hidden = false;
        choiceContinue.focus();
        void playWordAudio(current.word);
    }

    // Connect: match each word (left) with its translation (right). A word is
    // recorded right unless it was part of a wrong attempt.
    function renderConnect() {
        showBox("connect");
        status.textContent = "";
        undoBar.hidden = true; // Several answers at once; undo is per-record.
        connectContinueBar.hidden = true;
        connectWords.replaceChildren();
        connectTranslations.replaceChildren();
        current.selected = null;
        current.matched = 0;
        current.wrong = {};
        for (const pair of current.pairs) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "connect-cell";
            button.dataset.word = pair.word;
            button.textContent = pair.word;
            button.addEventListener("click", () => connectSelectWord(button));
            connectWords.append(button);
        }
        const shuffled = current.pairs.map((pair) => pair.translation);
        for (let i = shuffled.length - 1; i > 0; i -= 1) {
            const j = Math.floor(Math.random() * (i + 1));
            [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
        }
        for (const text of shuffled) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "connect-cell";
            button.dataset.translation = text;
            button.textContent = text;
            button.addEventListener("click", () =>
                connectSelectTranslation(button, text),
            );
            connectTranslations.append(button);
        }
        presentedAt = Date.now();
    }
    function connectSelectWord(button) {
        if (button.disabled) return;
        if (current.selected) current.selected.classList.remove("selected");
        current.selected = button;
        button.classList.add("selected");
    }
    async function connectSelectTranslation(button, translation) {
        if (button.disabled || !current || !current.selected) return;
        const word = current.selected.dataset.word;
        const pair = current.pairs.find((p) => p.word === word);
        if (pair && pair.translation === translation) {
            current.selected.disabled = true;
            current.selected.classList.remove("selected");
            current.selected.classList.add("matched");
            button.disabled = true;
            button.classList.add("matched");
            current.selected = null;
            current.matched += 1;
            await postAnswer(word, current.wrong[word] ? "n" : "y");
            if (current.matched === current.pairs.length) {
                connectContinueBar.hidden = false;
                connectContinue.focus();
            }
        } else {
            current.wrong[word] = true;
            button.classList.add("wrong-flash");
            setTimeout(() => button.classList.remove("wrong-flash"), 350);
        }
    }

    // Show the example sentence (word blanked) and one of its translations,
    // both kept off `/next` so the card appears immediately.
    function renderSentence() {
        sentence.replaceChildren();
        sentenceTranslation.replaceChildren();
        sentenceTranslation.hidden = true;
        if (!current || !current.sentence) {
            sentence.hidden = true;
            return;
        }
        sentence.hidden = false;
        sentence.textContent = "···";
        const item = current;
        item.sentence.then((data) => {
            if (current !== item) return;
            if (data && data.html) {
                sentence.innerHTML = data.html; // Safe fragment, word blanked.
                if (data.translation) {
                    sentenceTranslation.textContent = data.translation;
                    sentenceTranslation.hidden = false;
                }
            } else {
                sentence.textContent = "—";
            }
        });
    }

    function renderExternalLinks() {
        if (!current) {
            externalLinks.hidden = true;
            return;
        }
        const encoded = encodeURIComponent(current.word);
        const langName = languageName(language);
        const query = `Translate ${langName} word "${current.word}".`;
        googleLink.href =
            `https://www.google.com/search?q=${encodeURIComponent(query)}`;
        yandexLink.href =
            `https://translate.yandex.ru/?source_lang=${encodeURIComponent(language)}` +
            `&target_lang=en&text=${encoded}`;
        wiktionaryLink.href =
            `https://en.wiktionary.org/wiki/${encoded}` +
            `#${encodeURIComponent(langName.replace(/ /g, "_"))}`;
        const lower = current.word.toLowerCase();
        kaikkiLink.href =
            `https://kaikki.org/dictionary/${encodeURIComponent(langName)}/meaning/` +
            `${encodeURIComponent(lower.slice(0, 1))}/` +
            `${encodeURIComponent(lower.slice(0, 2))}/` +
            `${encodeURIComponent(lower)}.html`;
        externalLinks.hidden = false;
    }

    // Record one word's answer, carrying the current question's type and (for
    // type_word) the example shown and the time taken as provenance.
    async function postAnswer(word, response) {
        if (current && current.source === "new") handledNew.add(word);
        history.push({ word });
        await api(`${base}/answer`, {
            method: "POST",
            body: {
                word,
                response,
                question_type: current ? current.type : "type_word",
                sentence_id: current ? current.sentenceId ?? null : null,
                seconds: presentedAt ? (Date.now() - presentedAt) / 1000 : null,
            },
        });
    }

    // type_word answer. "I don't know" first reveals the word (the meaning is
    // already shown); a second action (Continue) records the wrong answer.
    async function recordTyped(response) {
        if (!current || current.type !== "type_word") return;
        if (response === "n" && !answeredWrong) {
            answeredWrong = true;
            wordEl.textContent = current.word;
            input.hidden = true;
            answers.hidden = true;
            continueBar.hidden = false;
            continueButton.focus();
            void playWordAudio(current.word); // Hear it once revealed.
            return;
        }
        if (response === "y") void playWordAudio(current.word); // Got it right.
        await postAnswer(current.word, response);
        await advance();
    }

    // Remove the most recent answer and re-present that word as a type_word
    // question to re-answer it.
    async function undo() {
        if (history.length === 0) return;
        const response = await api(`${base}/undo`, { method: "POST" });
        if (!response.ok) return;
        const { word: undone } = await response.json();
        if (!undone) return;
        history.pop();
        current = makeItem({ word: undone, source: "review" });
        renderCardStatus(null); // The word's history changed server-side.
        renderTeach();
    }

    // The new-word check: record know/don't-know in the `ask_lexicon`. "Know"
    // skips learning the word; "don't know" admits it and teaches it now.
    async function askAnswer(knows) {
        if (!current || !current.checkLexicon) return;
        const item = current;
        handledNew.add(item.word);
        await api(
            `/me/lexicons/${encodeURIComponent(item.checkLexicon)}/answer`,
            {
                method: "POST",
                body: { word: item.word, response: knows ? "know" : "dont" },
            },
        );
        if (knows) {
            await advance();
        } else {
            item.checkLexicon = null;
            current = item;
            renderTeach();
        }
    }

    // type_word: "I don't know" / "Skip" buttons and the reveal Continue.
    for (const button of answers.querySelectorAll("button")) {
        button.addEventListener("click", () =>
            recordTyped(button.dataset.response),
        );
    }
    continueButton.addEventListener("click", () => recordTyped("n"));
    // know: self-assess, then Continue advances.
    for (const button of knowAnswers.querySelectorAll("button")) {
        button.addEventListener("click", () =>
            knowSelfAssess(button.dataset.response === "y"),
        );
    }
    knowShow.addEventListener("click", () => void knowShowTranslation());
    knowContinue.addEventListener("click", advance);
    // choice / connect: Continue advances once the question is answered.
    choiceContinue.addEventListener("click", advance);
    connectContinue.addEventListener("click", advance);
    document.getElementById("undo").addEventListener("click", undo);
    document
        .getElementById("ask-know")
        .addEventListener("click", () => askAnswer(true));
    document
        .getElementById("ask-dont")
        .addEventListener("click", () => askAnswer(false));

    // On-screen buttons for letters of the learning language that the user's
    // physical keyboard may lack.
    function renderSymbolButtons(symbols) {
        symbolButtons.replaceChildren();
        symbolButtons.hidden = symbols.length === 0;
        for (const symbol of symbols) {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = symbol;
            // Keep the focus (and thus the caret) in the input: mousedown
            // would move it to the button before click fires.
            button.addEventListener("mousedown", (event) =>
                event.preventDefault(),
            );
            button.addEventListener("click", () => {
                if (input.hidden || input.disabled) return;
                const start = input.selectionStart ?? input.value.length;
                const end = input.selectionEnd ?? start;
                input.setRangeText(symbol, start, end, "end");
                input.focus();
                input.dispatchEvent(new Event("input"));
            });
            symbolButtons.append(button);
        }
    }

    // type_word: auto-accept the instant the typed text matches an accepted form.
    input.addEventListener("input", () => {
        if (!current || current.type !== "type_word") return;
        if ((current.accepted || []).includes(input.value)) {
            void recordTyped("y");
        }
    });

    // Keyboard: while typing, only Escape (give up) is a shortcut — letters go
    // to the field; otherwise a visible button's `data-key` triggers it.
    function shortcutButton(event) {
        if (event.ctrlKey || event.metaKey || event.altKey) return null;
        if (event.target === input || event.target.matches("textarea, select")) {
            return null;
        }
        let key;
        if (event.key === " ") key = " ";
        else if (event.key === "Enter") key = "enter";
        else key = event.key.toLowerCase();
        return (
            [...document.querySelectorAll(`button[data-key="${key}"]`)].find(
                (candidate) => !candidate.hidden && candidate.offsetParent,
            ) || null
        );
    }
    function isTypingEscape(event) {
        return (
            event.target === input &&
            event.key === "Escape" &&
            !event.ctrlKey &&
            !event.metaKey &&
            !event.altKey
        );
    }
    // Act on key *release*, so a held key can't rifle through several cards (see
    // the lexicon session). keydown arms the key and suppresses its default;
    // keyup fires it once. Arming only on a valid press means releasing the last
    // letter of a typed word never triggers the next card's shortcut.
    const armedKeys = new Set();
    document.addEventListener("keydown", (event) => {
        if (isTypingEscape(event) || shortcutButton(event)) {
            event.preventDefault();
            armedKeys.add(event.code);
        }
    });
    document.addEventListener("keyup", (event) => {
        if (!armedKeys.delete(event.code)) return;
        if (isTypingEscape(event)) {
            event.preventDefault();
            void recordTyped("n");
            return;
        }
        const button = shortcutButton(event);
        if (!button) return;
        event.preventDefault();
        button.classList.add("pressed");
        setTimeout(() => button.classList.remove("pressed"), 120);
        button.click();
    });

    status.textContent = "Loading…";
    const [dictionariesResponse, settingsResponse] = await Promise.all([
        api(`${base}/dictionaries`),
        api(`${base}/settings`),
    ]);
    if (dictionariesResponse.ok) dictionaries = await dictionariesResponse.json();
    if (settingsResponse.ok) {
        const settings = await settingsResponse.json();
        playAudio = settings.play_audio;
        renderSymbolButtons(settings.extra_symbols || "");
        knowWord.className =
            settings.learning_type === "symbol" ? "symbol" : "word";
    }
    await advance();
}

// Lexicon checking page.

async function initCheck() {
    requireAuth();
    const id = new URLSearchParams(location.search).get("lexicon");
    document.getElementById("lexicon-heading").replaceChildren(
        identifierSpan(id),
    );
    await runSession(
        `/me/lexicons/${encodeURIComponent(id)}`,
        "No more words to check.",
    );
}

// Learning repetition page.

async function initLearn() {
    requireAuth();
    const id = new URLSearchParams(location.search).get("learning");
    document
        .getElementById("learn-heading")
        .replaceChildren("Learn: ", identifierSpan(id));
    await runLearnSession(`/me/learnings/${encodeURIComponent(id)}`);
}

// Courses list page.

async function initCourses() {
    requireAuth();

    const status = document.getElementById("status");
    const table = document.getElementById("course-table");
    const rows = document.getElementById("course-rows");
    const response = await api("/me/courses");
    const courses = await response.json();

    if (courses.length === 0) {
        status.textContent = "No courses yet.";
    } else {
        status.textContent = "";
        table.hidden = false;
    }
    for (const course of courses) {
        const row = document.createElement("tr");

        const idCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = `course?course=${encodeURIComponent(
            course.course_id,
        )}`;
        link.textContent = course.name;
        idCell.appendChild(link);
        row.appendChild(idCell);

        for (const value of [
            languageName(course.language),
            course.learning_count,
        ]) {
            const cell = document.createElement("td");
            cell.textContent = value;
            row.appendChild(cell);
        }

        rows.appendChild(row);
    }
}

// Course detail page.

async function initCourse() {
    requireAuth();

    const courseId = new URLSearchParams(location.search).get("course");
    const status = document.getElementById("status");
    const table = document.getElementById("learning-table");
    const rows = document.getElementById("learning-rows");
    const response = await api(
        `/me/courses/${encodeURIComponent(courseId)}`,
    );
    if (!response.ok) {
        status.textContent = "Could not load course.";
        return;
    }
    const course = await response.json();
    status.textContent = "";

    document.getElementById("course-heading").textContent =
        `Course: ${course.name}`;
    document.getElementById("add-learning-link").href =
        `new-learning?course=${encodeURIComponent(courseId)}`;

    // Settings: currently just the course's name (its language is fixed).
    const settingsSection = document.getElementById("settings-section");
    const settingsForm = document.getElementById("settings-form");
    const nameInput = document.getElementById("setting-name");
    const settingsStatus = document.getElementById("settings-status");
    nameInput.value = course.name;
    settingsSection.hidden = false;
    settingsForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        settingsStatus.textContent = "Saving…";
        const result = await api(
            `/me/courses/${encodeURIComponent(courseId)}`,
            { method: "PATCH", body: { name: nameInput.value.trim() } },
        );
        if (result.ok) {
            const updated = await result.json();
            document.getElementById("course-heading").textContent =
                `Course: ${updated.name}`;
            settingsStatus.textContent = "Saved.";
        } else {
            const { detail } = await result.json().catch(() => ({}));
            settingsStatus.textContent = detail || "Could not save settings.";
        }
    });

    if (course.learnings.length > 0) table.hidden = false;
    for (const learning of course.learnings) {
        const row = document.createElement("tr");

        const idCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = `learning?learning=${encodeURIComponent(
            learning.learning_id,
        )}&course=${encodeURIComponent(courseId)}`;
        link.textContent = learning.name;
        idCell.appendChild(link);
        row.appendChild(idCell);

        for (const value of [
            learning.learning_type === "symbol" ? "Alphabet" : "Vocabulary",
            learning.words,
            learning.answers,
        ]) {
            const cell = document.createElement("td");
            cell.textContent = value;
            row.appendChild(cell);
        }

        rows.appendChild(row);
    }

    // Delete: only allowed while the course has no learnings left.
    const danger = document.getElementById("danger");
    const deleteStatus = document.getElementById("delete-status");
    danger.hidden = false;
    document
        .getElementById("delete-course")
        .addEventListener("click", async () => {
            if (
                !confirm(`Delete course "${course.name}"? This cannot be undone.`)
            ) {
                return;
            }
            deleteStatus.textContent = "Deleting…";
            const result = await api(
                `/me/courses/${encodeURIComponent(courseId)}`,
                { method: "DELETE" },
            );
            if (result.ok) {
                location.href = "courses";
            } else {
                const { detail } = await result.json().catch(() => ({}));
                deleteStatus.textContent =
                    detail || "Could not delete course.";
            }
        });
}

// Learning detail page (settings, statistics, delete).

async function initLearning() {
    requireAuth();

    const params = new URLSearchParams(location.search);
    const learningId = params.get("learning");
    const courseId = params.get("course");
    if (courseId) {
        document.getElementById("back-to-course").href =
            `course?course=${encodeURIComponent(courseId)}`;
    }
    document.getElementById("learning-heading").textContent =
        `Learning: ${learningId}`;
    document.getElementById("learn-link").href =
        `learn?learning=${encodeURIComponent(learningId)}`;

    const status = document.getElementById("status");
    const stats = document.getElementById("stats");
    const response = await api(
        `/me/learnings/${encodeURIComponent(learningId)}/stats`,
    );
    if (!response.ok) {
        status.textContent = "Could not load statistics.";
        return;
    }
    const s = await response.json();
    status.textContent = "";

    const rows = [
        ["Name", s.name],
        ["Language", languageName(s.learning_language)],
        ["Words being learned", s.learning],
        ["Due for repetition", s.to_repeat],
        ["New words allowed today", s.to_add],
        ["Added today", s.added_today],
        ["Total answers", s.answers],
        ["Actions (right/wrong)", s.actions],
    ];
    renderDefinitionList(stats, rows);

    await setupLearningSettings(learningId);

    // Delete: removes the learning and all its history, then returns to the
    // parent course (or the courses list, if it isn't known).
    const danger = document.getElementById("danger");
    const deleteStatus = document.getElementById("delete-status");
    danger.hidden = false;
    document
        .getElementById("delete-learning")
        .addEventListener("click", async () => {
            if (
                !confirm(
                    `Delete learning "${learningId}" and all its history? ` +
                        "This cannot be undone.",
                )
            ) {
                return;
            }
            deleteStatus.textContent = "Deleting…";
            const result = await api(
                `/me/learnings/${encodeURIComponent(learningId)}`,
                { method: "DELETE" },
            );
            if (result.ok) {
                location.href = courseId
                    ? `course?course=${encodeURIComponent(courseId)}`
                    : "courses";
            } else {
                deleteStatus.textContent = "Could not delete learning.";
            }
        });
}

// Fill and wire the learning settings form: name, translation targets (which
// regenerate dictionaries/sentences/audio on save), the daily new-word limit,
// allowed question types, and the two optional lexicon references (skip
// already-known words / ask about unseen ones first). Pre-filled from the
// learning's current settings.
async function setupLearningSettings(learningId) {
    const base = `/me/learnings/${encodeURIComponent(learningId)}`;
    const section = document.getElementById("settings-section");
    const learningTypeLabel = document.getElementById(
        "setting-learning-type",
    );
    const form = document.getElementById("settings-form");
    const wordFields = form.querySelector(".learning-word-fields");
    const nameInput = document.getElementById("setting-name");
    const targets = document.getElementById("setting-targets");
    const maxInput = document.getElementById("setting-max");
    const playAudioInput = document.getElementById("setting-play-audio");
    const questionTypesContainer = document.getElementById(
        "setting-question-types",
    );
    const lexiconSelect = document.getElementById("setting-lexicon");
    const askLexiconSelect = document.getElementById("setting-ask-lexicon");
    const settingsStatus = document.getElementById("settings-status");

    const [
        settingsResponse,
        targetResponse,
        questionTypeResponse,
        lexiconResponse,
    ] = await Promise.all([
        api(`${base}/settings`),
        api("/translation-languages"),
        api("/question-types"),
        api("/me/lexicons"),
    ]);
    if (!settingsResponse.ok) return;
    const settings = await settingsResponse.json();
    const isWord = settings.learning_type === "word";

    learningTypeLabel.textContent = isWord ? "vocabulary" : "alphabet";
    wordFields.hidden = !isWord;
    targets.required = isWord;

    nameInput.value = settings.name;
    maxInput.value = settings.max_for_day;
    playAudioInput.checked = settings.play_audio;
    fillLanguageSelect(
        targets,
        await targetResponse.json(),
        new Set(settings.translation_languages),
    );

    const questionTypes = await questionTypeResponse.json();
    renderQuestionTypeCheckboxes(
        questionTypesContainer,
        "setting-question-type",
        questionTypes,
        new Set(settings.question_types),
    );

    const lexicons = await lexiconResponse.json();
    fillLearningLexiconSelect(
        lexiconSelect,
        lexicons,
        settings.learning_language,
        settings.lexicon_id,
    );
    fillLearningLexiconSelect(
        askLexiconSelect,
        lexicons,
        settings.learning_language,
        settings.ask_lexicon_id,
    );

    section.hidden = false;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const questionTypesChecked = checkedQuestionTypes(
            questionTypesContainer,
        );
        if (questionTypesChecked.length === 0) {
            settingsStatus.textContent = "Pick at least one question type.";
            return;
        }
        const body = {
            name: nameInput.value.trim(),
            max_for_day: Number(maxInput.value),
            play_audio: playAudioInput.checked,
            // Every type checked means "no restriction"; send an empty list
            // so the server clears any previously narrowed set.
            question_types:
                questionTypesChecked.length === questionTypes.length
                    ? []
                    : questionTypesChecked,
        };
        if (isWord) {
            const translationLanguages = Array.from(
                targets.selectedOptions,
                (option) => option.value,
            );
            if (translationLanguages.length === 0) {
                settingsStatus.textContent =
                    "Pick at least one language to translate into.";
                return;
            }
            body.translation_languages = translationLanguages;
            body.lexicon_id = lexiconSelect.value;
            body.ask_lexicon_id = askLexiconSelect.value;
        }
        settingsStatus.textContent = "Saving…";
        const result = await api(`${base}/settings`, {
            method: "PATCH",
            body,
        });
        if (result.ok) {
            settingsStatus.textContent = "Saved.";
        } else {
            const { detail } = await result.json().catch(() => ({}));
            settingsStatus.textContent = detail || "Could not save settings.";
        }
    });
}

// Profile page.

async function initProfile() {
    requireAuth();

    const status = document.getElementById("status");
    const profile = document.getElementById("profile");
    const response = await api("/me");
    if (!response.ok) {
        status.textContent = "Could not load profile.";
        return;
    }
    const me = await response.json();
    status.textContent = "";
    profile.hidden = false;
    renderDefinitionList(profile, [
        ["User", me.user_id],
        ["Name", me.name],
        ["Email", me.email || "—"],
    ]);

    // Appearance switchers: persist the choice and apply it immediately.
    // `STYLE_KEY`, `THEME_KEY`, and `applyAppearance` come from theme.js.
    for (const [select, key] of [
        [document.getElementById("style-select"), STYLE_KEY],
        [document.getElementById("theme-select"), THEME_KEY],
    ]) {
        select.value = localStorage.getItem(key) || select.options[0].value;
        select.addEventListener("change", () => {
            localStorage.setItem(key, select.value);
            applyAppearance();
        });
    }

    // Download all of the user's data as a ZIP. The endpoint needs the bearer
    // token, so fetch it as a blob and trigger a download rather than linking.
    const exportStatus = document.getElementById("export-status");
    document
        .getElementById("export-data")
        .addEventListener("click", async () => {
            exportStatus.textContent = "Preparing your archive…";
            const result = await api("/me/export");
            if (!result.ok) {
                exportStatus.textContent = "Could not export your data.";
                return;
            }
            const url = URL.createObjectURL(await result.blob());
            const link = document.createElement("a");
            link.href = url;
            link.download = `${me.user_id}-emmio-data.zip`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
            exportStatus.textContent = "Downloaded.";
        });

    // Change password: verify the current one server-side, enforce the new
    // one's minimum length, and clear the fields on success. The access token
    // stays valid (a stateless JWT can't be re-signed), so no re-login.
    const passwordStatus = document.getElementById("password-status");
    document
        .getElementById("password-form")
        .addEventListener("submit", async (event) => {
            event.preventDefault();
            const data = new FormData(event.target);
            passwordStatus.textContent = "Saving…";
            const result = await api("/me/password", {
                method: "POST",
                body: {
                    current_password: data.get("current_password"),
                    new_password: data.get("new_password"),
                },
            });
            if (result.ok) {
                event.target.reset();
                passwordStatus.textContent = "Password changed.";
            } else {
                const { detail } = await result.json().catch(() => ({}));
                passwordStatus.textContent =
                    typeof detail === "string"
                        ? detail
                        : "Could not change password.";
            }
        });

    // Deleting the account is irreversible; confirm, then drop the now-useless
    // token and return to login.
    const deleteStatus = document.getElementById("delete-status");
    document
        .getElementById("delete-account")
        .addEventListener("click", async () => {
            if (
                !confirm(
                    "Delete your account and all of your data? This cannot " +
                        "be undone.",
                )
            ) {
                return;
            }
            deleteStatus.textContent = "Deleting…";
            const result = await api("/me", { method: "DELETE" });
            if (result.ok) {
                clearToken();
                location.href = "login";
            } else {
                deleteStatus.textContent = "Could not delete account.";
            }
        });
}

// Dispatch on the page.

document.addEventListener("DOMContentLoaded", () => {
    // Log out lives on the profile page; wire it when present.
    const logout = document.getElementById("logout");
    if (logout) {
        logout.addEventListener("click", () => {
            clearToken();
            location.href = "login";
        });
    }

    const page = document.body.dataset.page;
    if (page === "landing") initLanding();
    else if (page === "login") initLogin();
    else if (page === "register") initRegister();
    else if (page === "home") initHome();
    else if (page === "language") initLanguage();
    else if (page === "lexicons") initLexicons();
    else if (page === "lexicon") initLexicon();
    else if (page === "new-lexicon") initNewLexicon();
    else if (page === "check") initCheck();
    else if (page === "courses") initCourses();
    else if (page === "course") initCourse();
    else if (page === "new-course") initNewCourse();
    else if (page === "new-learning") initNewLearning();
    else if (page === "learning") initLearning();
    else if (page === "learn") initLearn();
    else if (page === "profile") initProfile();
});
