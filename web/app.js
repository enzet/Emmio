"use strict";

// Minimal vanilla-JS client for the Emmio API. Holds the access token in
// localStorage and attaches it as a bearer token on each request. No build
// step, no framework; pages dispatch on `<body data-page="...">`.

const API = "/api/v1";
const TOKEN_KEY = "emmio_token";

// "Book" icon from @enzet/roentgen, inlined so it inherits the link's color via
// `currentColor` (a referenced `<img>` can't follow the host page's color).
const BOOK_ICON =
    '<svg class="button-icon" viewBox="0 0 16 16" aria-hidden="true">' +
    '<path d="M 4.5,2.0 C 3.671,2.0 3.0,2.672 3.0,3.5 L 3.0,12.5 C 3.0,13.328 ' +
    "3.671,14.0 4.498,14.0 L 12.5,14.0 C 12.777,14.0 13.0,13.776 13.0,13.5 C " +
    "13.0,13.224 12.777,13.0 12.501,13.0 L 4.5,13.0 C 4.223,13.0 4.0,12.776 " +
    "4.0,12.5 L 4.0,11.501 C 4.0,11.224 4.223,11.0 4.499,11.0 L 12.5,11.0 C " +
    "12.777,11.0 13.0,10.776 13.0,10.5 L 13.0,2.501 C 13.0,2.224 12.777,2.0 " +
    "12.501,2.0 L 5.5,2.0 L 4.5,2.0 M 5.499,4.0 L 10.5,4.0 C 10.777,4.001 " +
    "11.0,4.224 11.0,4.5 C 11.0,4.776 10.777,4.999 10.501,5.0 L 5.5,5.0 C " +
    "5.223,4.999 5.0,4.776 5.0,4.5 C 5.0,4.224 5.223,4.001 5.499,4.0 M " +
    "5.499,6.0 L 8.5,6.0 C 8.777,6.001 9.0,6.224 9.0,6.5 C 9.0,6.776 8.777,6.999 " +
    "8.501,7.0 L 5.5,7.0 C 5.223,6.999 5.0,6.776 5.0,6.5 C 5.0,6.224 5.223,6.001 " +
    "5.499,6.0 M 5.499,8.0 L 9.5,8.0 C 9.777,8.0 10.0,8.224 10.0,8.5 C 10.0,8.776 " +
    "9.777,9.0 9.501,9.0 L 5.5,9.0 C 5.223,9.0 5.0,8.776 5.0,8.5 C 5.0,8.224 " +
    '5.223,8.0 5.499,8.0" fill="currentColor" /></svg>';

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
function emmioLevel(rate) {
    if (rate === null || rate < 2) return "—";
    if (rate < 3) return "A1";
    if (rate < 4) return "A2";
    if (rate < 5) return "B1";
    if (rate < 6) return "B2";
    if (rate < 7) return "C1";
    return "C2";
}

// Append a `<dt>`/`<dd>` pair to `container` for each `[label, value]` row.
// Shared by the lexicon, course, and profile detail pages.
function renderDefinitionList(container, rows) {
    for (const [label, value] of rows) {
        const term = document.createElement("dt");
        term.textContent = label;
        const description = document.createElement("dd");
        description.textContent = value;
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
    const response = await api("/me/languages");
    const languages = await response.json();

    // The user's courses, grouped by learning language, so each language row
    // can list the courses available to study for it.
    const coursesResponse = await api("/me/courses");
    const courses = coursesResponse.ok ? await coursesResponse.json() : [];
    const coursesByLanguage = new Map();
    for (const course of courses) {
        const list = coursesByLanguage.get(course.learning_language) || [];
        list.push(course);
        coursesByLanguage.set(course.learning_language, list);
    }

    // Nothing yet: welcome the user and offer to create their first lexicon.
    // The dashboard shows for any language the user has a main lexicon *or* a
    // course for.
    if (languages.length === 0 && courses.length === 0) {
        document.getElementById("welcome").hidden = false;
        await setupCreateLexicon(
            "create-lexicon-form",
            "new-lexicon-language",
            "create-status",
        );
        return;
    }
    document.getElementById("languages").hidden = false;
    status.textContent = "";
    table.hidden = false;

    // Render one language row. `entry` is its main-lexicon stats (`/me/languages`)
    // or `null` when the language only has courses; `courseList` are its courses.
    function renderLanguageRow(language, entry, courseList) {
        const row = document.createElement("tr");

        const nameCell = document.createElement("td");
        const code = document.createElement("span");
        code.className = "language-code";
        code.textContent = language;
        nameCell.appendChild(code);
        if (entry) {
            const link = document.createElement("a");
            link.href = `lexicon?lexicon=${encodeURIComponent(
                entry.lexicon_id,
            )}`;
            link.textContent = languageName(language);
            nameCell.appendChild(link);
        } else {
            nameCell.appendChild(
                document.createTextNode(languageName(language)),
            );
        }
        row.appendChild(nameCell);

        const rateCell = document.createElement("td");
        rateCell.textContent =
            entry && entry.rate !== null ? entry.rate.toFixed(2) : "—";
        rateCell.style.textAlign = "right";
        rateCell.style.fontVariantNumeric = "tabular-nums";
        row.appendChild(rateCell);

        // Emmio-specific language level derived from the rate.
        const levelCell = document.createElement("td");
        levelCell.textContent = entry ? emmioLevel(entry.rate) : "—";
        row.appendChild(levelCell);

        // Lexicon column: when checks are still wanted this week, the number
        // remaining and a "Check" button; otherwise the time until the next
        // check becomes available (last "don't know" answer plus one week).
        const lexiconCell = document.createElement("td");
        if (entry && entry.weekly_remaining > 0) {
            const remaining = document.createElement("span");
            remaining.textContent = entry.weekly_remaining;
            remaining.style.marginRight = "0.5em";
            lexiconCell.appendChild(remaining);
            const check = document.createElement("a");
            check.className = "button";
            check.href = `check?lexicon=${encodeURIComponent(
                entry.lexicon_id,
            )}`;
            check.insertAdjacentHTML("afterbegin", BOOK_ICON);
            check.appendChild(document.createTextNode("Check"));
            lexiconCell.appendChild(check);
        } else if (entry && entry.last_dont_know) {
            const nextCheck =
                new Date(entry.last_dont_know).getTime() + 7 * 86400000;
            lexiconCell.textContent = formatCountdown(nextCheck - Date.now());
        }
        row.appendChild(lexiconCell);

        // Courses to study for this language, each linking to its session.
        const coursesCell = document.createElement("td");
        coursesCell.className = "courses-cell";
        for (const course of courseList) {
            const learn = document.createElement("a");
            learn.href = `learn?course=${encodeURIComponent(
                course.course_id,
            )}`;
            learn.textContent = course.name;
            coursesCell.appendChild(learn);
        }
        row.appendChild(coursesCell);

        rows.appendChild(row);
    }

    // Languages with a main lexicon first (already sorted by rate), then the
    // course-only ones, alphabetically.
    const rated = new Set();
    for (const entry of languages) {
        rated.add(entry.language);
        renderLanguageRow(
            entry.language,
            entry,
            coursesByLanguage.get(entry.language) || [],
        );
    }
    const courseOnly = [...coursesByLanguage.keys()]
        .filter((language) => !rated.has(language))
        .sort((a, b) => languageName(a).localeCompare(languageName(b)));
    for (const language of courseOnly) {
        renderLanguageRow(language, null, coursesByLanguage.get(language));
    }
    // Vocabulary-level history of the main lexicons, rendered server-side as
    // SVG. Inlined rather than an `<img src>` because the endpoint needs the
    // bearer token and inline SVG scales with the page CSS. 204 means there
    // are not enough answers to plot yet.
    const graphResponse = await api("/me/lexicons/graph");
    if (graphResponse.status === 200) {
        const figure = document.getElementById("lexicon-graph");
        figure.innerHTML = await graphResponse.text();
        figure.hidden = false;
    }

    await setupCreateLexicon(
        "add-lexicon-form",
        "add-lexicon-language",
        "add-status",
    );
    await setupCreateCourse(
        "add-course-form",
        "add-course-language",
        "add-course-status",
    );
}

// Wire up a "create lexicon" form: fill its language selector from the
// available frequency-list languages, and on submit create the lexicon (which
// is set as main, with the chosen selection strategy) and open it. Shared by
// the empty-state welcome form and the dashboard's "Add a lexicon" form.
async function setupCreateLexicon(formId, selectId, statusId) {
    const form = document.getElementById(formId);
    const select = document.getElementById(selectId);
    const targets = form.querySelector(".translation-languages");
    const selection = form.querySelector(".lexicon-selection");
    const createStatus = document.getElementById(statusId);

    const [response, targetResponse, strategyResponse] = await Promise.all([
        api("/lexicon-languages"),
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

    fillLanguageSelect(select, available);

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

// Wire up an "add a course" form: fill its language selector from the languages
// available for learning (the same ones a lexicon can use — a frequency list to
// draw new words from and Tatoeba sentences for examples), and on submit create
// the course and open its learning session.
async function setupCreateCourse(formId, selectId, statusId) {
    const form = document.getElementById(formId);
    const select = document.getElementById(selectId);
    const targets = form.querySelector(".translation-languages");
    const createStatus = document.getElementById(statusId);

    const [response, targetResponse] = await Promise.all([
        api("/lexicon-languages"),
        api("/translation-languages"),
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

    fillLanguageSelect(select, available);
    fillLanguageSelect(targets, await targetResponse.json(), "en");

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
        const result = await api("/me/courses", {
            method: "POST",
            body: {
                language: select.value,
                translation_languages: translationLanguages,
            },
        });
        if (result.ok) {
            const { course_id } = await result.json();
            location.href = `learn?course=${encodeURIComponent(course_id)}`;
        } else {
            const { detail } = await result.json().catch(() => ({}));
            createStatus.textContent = detail || "Could not create course.";
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
        return;
    }
    status.textContent = "";
    table.hidden = false;
    for (const lexicon of lexicons) {
        const row = document.createElement("tr");

        const idCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = `lexicon?lexicon=${encodeURIComponent(
            lexicon.lexicon_id,
        )}`;
        // A leading star marks the main lexicon for its language.
        link.textContent =
            (lexicon.is_main ? "★ " : "") +
            (lexicon.name || lexicon.lexicon_id);
        if (lexicon.name) link.title = lexicon.lexicon_id;
        idCell.appendChild(link);
        row.appendChild(idCell);

        for (const value of [
            languageName(lexicon.language),
            lexicon.selection || "",
            lexicon.rate === null ? "—" : lexicon.rate.toFixed(1),
            lexicon.words,
            lexicon.dont_last_week,
        ]) {
            const cell = document.createElement("td");
            cell.textContent = value;
            row.appendChild(cell);
        }

        rows.appendChild(row);
    }
}

// Lexicon detail page.

async function initLexicon() {
    requireAuth();

    const lexiconId = new URLSearchParams(location.search).get("lexicon");
    document.getElementById("lexicon-heading").textContent =
        `Lexicon: ${lexiconId}`;
    document.getElementById("check-link").href =
        `check?lexicon=${encodeURIComponent(lexiconId)}`;

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
        ["Selection", s.selection || "—"],
        ["Words checked", s.words],
        ["Known", s.known],
        ["Don't know", s.dont_know],
        [
            "Vocabulary rate",
            s.rate === null ? "not enough data" : s.rate.toFixed(1),
        ],
        ["Precision (total)", s.precision],
        ["Precision (last 7 days)", s.dont_last_week],
        ["Weekly goal", s.precision_per_week],
    ];
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
// moves the lexicon's URL, so the page redirects after a rename), translation
// targets (which regenerate the dictionary/sentence config on save — also
// backfilling lexicons created before targets were auto-configured), and the
// weekly goal. The lexicon's identity (language, selection, frequency list)
// is immutable and not shown here. Pre-filled from the lexicon's current
// settings.
async function setupLexiconSettings(lexiconId) {
    const base = `/me/lexicons/${encodeURIComponent(lexiconId)}`;
    const section = document.getElementById("settings-section");
    const form = document.getElementById("settings-form");
    const nameInput = document.getElementById("setting-name");
    const idInput = document.getElementById("setting-id");
    const targets = document.getElementById("setting-targets");
    const precisionInput = document.getElementById("setting-precision");
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
    precisionInput.value = settings.precision_per_week;
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
                precision_per_week: Number(precisionInput.value),
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
            document.getElementById("lexicon-heading").textContent =
                saved.name || `Lexicon: ${saved.lexicon_id}`;
            settingsStatus.textContent = "Saved.";
        } else {
            const { detail } = await result.json().catch(() => ({}));
            settingsStatus.textContent = detail || "Could not save settings.";
        }
    });
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

    // Live "r = 7.23 ± 0.14" estimate, computed server-side by the estimator
    // matching the lexicon's selection strategy and refreshed after every
    // answer. Fire-and-forget: a stale response (superseded by a later
    // request) is dropped, and the element is absent on non-check pages.
    const rateEstimate = document.getElementById("rate-estimate");
    let rateRequest = 0;

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

    async function refreshRateEstimate() {
        if (!rateEstimate) return;
        const token = ++rateRequest;
        const response = await api(`${base}/rate-estimate`);
        if (token !== rateRequest || !response.ok) return;
        const estimate = await response.json();
        if (token !== rateRequest) return;
        if (estimate.rate === null) {
            rateEstimate.hidden = true;
            return;
        }
        rateEstimate.textContent =
            `r = ${estimate.rate.toFixed(2)} ± ${estimate.sd.toFixed(2)}`;
        rateEstimate.title = `${estimate.method[0].toUpperCase()}${estimate.method.slice(1)} estimate`;
        rateEstimate.hidden = false;
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
    // Re-renders if the word is already revealed. Ignored once the user has
    // moved to another word.
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
        if (revealed) renderRevealed(item);
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
        revealed = false;
        showButton.hidden = false;
        showButton.disabled = true;
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
        const query = `translate ${langName} word "${current.word}"`;
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

    // Move to the next queued word, topping the queue back up in the
    // background so the wait is hidden behind the user's reading time.
    async function advance() {
        if (queue.length === 0) {
            // No word prefetched yet (first load, or the buffer ran dry): show
            // the dots in the word slot while `/next` is in flight.
            word.replaceChildren(loadingDots());
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
        if (!current) return;
        const answered = current.word;
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
        await api(`${base}/answer`, {
            method: "POST",
            body: { word: answered, response, to_skip: toSkip },
        });
        void refreshRateEstimate();
        await advance();
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

    // Reveal the current word's translation. From here on the area re-renders
    // as each remaining dictionary resolves (see `onTranslationProgress`).
    function showTranslation() {
        if (!current) return;
        revealed = true;
        if (!current.results) attachTranslation(current);
        renderRevealed(current);
    }

    // Render every dictionary that has resolved so far for `item`, in
    // configured order (so a fast dictionary that resolves later still keeps
    // its place). Shows "Loading…" until the first arrives and "No
    // translation found." once every dictionary has resolved empty.
    function renderRevealed(item) {
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
        .addEventListener("click", showTranslation);
    document.getElementById("undo").addEventListener("click", undo);

    // Keyboard shortcuts: each button's `data-key` triggers a click (matches
    // the CLI), plus space to reveal the translation.
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
    void refreshRateEstimate();
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

    // Know box.
    const knowBox = document.getElementById("know-box");
    const knowWord = document.getElementById("know-word");
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
    let playAudio = true; // Course setting: play pronunciation audio.

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
        return makeItem({
            word: data.word,
            accepted: data.accepted,
            source: "new",
            checkLexicon: data.check_lexicon,
        });
    }

    // Present a server-chosen review question by its type.
    function presentReview(q) {
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
    // chosen by the server), then a new word (taught as type_word, possibly
    // after a know/don't-know lexicon check).
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
            current = item;
            if (item.checkLexicon) renderAsk();
            else renderTeach();
            return;
        }
        current = null;
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
    // meaning is then revealed before continuing.
    function renderKnow() {
        showBox("know");
        status.textContent = "";
        undoBar.hidden = history.length === 0;
        if (history.length) {
            undoWord.textContent = history[history.length - 1].word;
        }
        knowWord.textContent = current.word;
        knowAnswers.hidden = false;
        knowMeaning.hidden = true;
        knowMeaning.replaceChildren();
        knowContinueBar.hidden = true;
        current.pendingResponse = null;
        presentedAt = Date.now();
    }
    async function knowSelfAssess(knows) {
        if (!current || current.type !== "know" || current.pendingResponse) {
            return;
        }
        current.pendingResponse = knows ? "y" : "n";
        knowAnswers.hidden = true;
        await postAnswer(current.word, current.pendingResponse);
        // Reveal the full meaning (word shown) so the user learns/confirms it.
        const item = current;
        knowMeaning.hidden = false;
        knowMeaning.textContent = "Loading…";
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
        const query = `translate ${langName} word "${current.word}"`;
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
        playAudio = (await settingsResponse.json()).play_audio;
    }
    await advance();
}

// Lexicon checking page.

async function initCheck() {
    requireAuth();
    const id = new URLSearchParams(location.search).get("lexicon");
    document.getElementById("lexicon-heading").textContent =
        `${id}`;
    await runSession(
        `/me/lexicons/${encodeURIComponent(id)}`,
        "No more words to check.",
    );
}

// Learning repetition page.

async function initLearn() {
    requireAuth();
    const id = new URLSearchParams(location.search).get("course");
    document.getElementById("learn-heading").textContent = `Learn: ${id}`;
    await runLearnSession(`/me/courses/${encodeURIComponent(id)}`);
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
        return;
    }
    status.textContent = "";
    table.hidden = false;
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
            languageName(course.learning_language),
            course.words,
            course.answers,
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
    document.getElementById("course-heading").textContent =
        `Course: ${courseId}`;
    document.getElementById("learn-link").href =
        `learn?course=${encodeURIComponent(courseId)}`;

    const status = document.getElementById("status");
    const stats = document.getElementById("stats");
    const response = await api(
        `/me/courses/${encodeURIComponent(courseId)}/stats`,
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

    await setupCourseSettings(courseId);

    // Delete: removes the course and all its history, then returns to the list.
    const danger = document.getElementById("danger");
    const deleteStatus = document.getElementById("delete-status");
    danger.hidden = false;
    document
        .getElementById("delete-course")
        .addEventListener("click", async () => {
            if (
                !confirm(
                    `Delete course "${courseId}" and all its history? This ` +
                        "cannot be undone.",
                )
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
                deleteStatus.textContent = "Could not delete course.";
            }
        });
}

// Fill and wire the course settings form: name, translation targets (which
// regenerate dictionaries/sentences/audio on save), and the daily new-word
// limit. Pre-filled from the course's current settings.
async function setupCourseSettings(courseId) {
    const base = `/me/courses/${encodeURIComponent(courseId)}`;
    const section = document.getElementById("settings-section");
    const form = document.getElementById("settings-form");
    const nameInput = document.getElementById("setting-name");
    const targets = document.getElementById("setting-targets");
    const maxInput = document.getElementById("setting-max");
    const playAudioInput = document.getElementById("setting-play-audio");
    const settingsStatus = document.getElementById("settings-status");

    const [settingsResponse, targetResponse] = await Promise.all([
        api(`${base}/settings`),
        api("/translation-languages"),
    ]);
    if (!settingsResponse.ok) return;
    const settings = await settingsResponse.json();

    nameInput.value = settings.name;
    maxInput.value = settings.max_for_day;
    playAudioInput.checked = settings.play_audio;
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
                name: nameInput.value.trim(),
                translation_languages: translationLanguages,
                max_for_day: Number(maxInput.value),
                play_audio: playAudioInput.checked,
            },
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
    else if (page === "lexicons") initLexicons();
    else if (page === "lexicon") initLexicon();
    else if (page === "check") initCheck();
    else if (page === "courses") initCourses();
    else if (page === "course") initCourse();
    else if (page === "learn") initLearn();
    else if (page === "profile") initProfile();
});
