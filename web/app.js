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

// Fill a `<select>` with one `<option>` per language, sorted by display name.
// `entries` is a list of API rows carrying a `language` ISO code; `selectCode`
// optionally preselects the matching option.
function fillLanguageSelect(select, entries, selectCode) {
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
            if (entry.code === selectCode) option.selected = true;
            select.appendChild(option);
        });
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

    // No main lexicon yet: welcome the user and offer to create their first
    // one. Otherwise show the languages dashboard, with an "Add a lexicon"
    // control to create further ones.
    if (languages.length === 0) {
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
    for (const entry of languages) {
        const row = document.createElement("tr");

        const nameCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = `lexicon?lexicon=${encodeURIComponent(
            entry.lexicon_id,
        )}`;
        link.textContent = languageName(entry.language);
        nameCell.appendChild(link);
        row.appendChild(nameCell);

        const rateCell = document.createElement("td");
        rateCell.textContent =
            entry.rate === null ? "—" : entry.rate.toFixed(1);
        row.appendChild(rateCell);

        // "Don't know" answers still wanted this week; blank when on target.
        const remainingCell = document.createElement("td");
        remainingCell.textContent =
            entry.weekly_remaining <= 0 ? "" : entry.weekly_remaining;
        row.appendChild(remainingCell);

        const checkCell = document.createElement("td");
        if (entry.weekly_remaining > 0) {
            const check = document.createElement("a");
            check.className = "button";
            check.href = `check?lexicon=${encodeURIComponent(
                entry.lexicon_id,
            )}`;
            check.insertAdjacentHTML("afterbegin", BOOK_ICON);
            check.appendChild(document.createTextNode("Check"));
            checkCell.appendChild(check);
        }
        row.appendChild(checkCell);

        rows.appendChild(row);
    }
    await setupCreateLexicon(
        "add-lexicon-form",
        "add-lexicon-language",
        "add-status",
    );
}

// Wire up a "create lexicon" form: fill its language selector from the
// available frequency-list languages, and on submit create the lexicon (which
// is set as main, with `frequency` selection) and open it. Shared by the
// empty-state welcome form and the dashboard's "Add a lexicon" form.
async function setupCreateLexicon(formId, selectId, statusId) {
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

    // Fill the "translate into" picker with every known language; preselect
    // English as the most common target.
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
        const result = await api("/me/lexicons", {
            method: "POST",
            body: {
                language: select.value,
                translation_languages: translationLanguages,
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
            (lexicon.is_main ? "★ " : "") + lexicon.lexicon_id;
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
    let current = null; // The item on screen.
    let revealed = false; // Whether the current word's translation is shown.
    let language = null; // ISO code of the session's language (from `/next`).

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
    // so the server never hands back a duplicate.
    async function fill() {
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
        for (const card of batch.words) {
            const item = {
                word: card.word,
                lastResponse: card.last_response,
                lastTime: card.last_time,
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
        sentence.replaceChildren();
        if (!current || !current.sentence) {
            sentence.hidden = true;
            return;
        }
        sentence.hidden = false;
        sentence.textContent = "···";
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
        if (queue.length === 0) await fill();
        current = queue.shift() || null;
        render();
        void fill();
    }

    async function answer(response, toSkip = false) {
        if (!current) return;
        const answered = current.word;
        history.push({ word: answered });
        await api(`${base}/answer`, {
            method: "POST",
            body: { word: answered, response, to_skip: toSkip },
        });
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
        history.pop();
        if (current) queue.unshift(current);
        current = { word: undone, results: null, sentence: null };
        attachTranslation(current);
        attachSentence(current);
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
            translation.textContent = "Loading…";
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
    document.addEventListener("keydown", (event) => {
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        if (event.target.matches("input, textarea, select")) return;
        const key = event.key === " " ? " " : event.key.toLowerCase();
        const button = document.querySelector(`button[data-key="${key}"]`);
        // Skip a hidden button (e.g. the reveal button once it has been
        // replaced by the "No translation found." notice).
        if (button && !button.hidden) {
            event.preventDefault();
            button.click();
        }
    });

    status.textContent = "Loading…";
    // Load the dictionary list first so the per-word prefetch knows which
    // dictionaries to request; an empty list just means no translations.
    const dictionariesResponse = await api(`${base}/dictionaries`);
    if (dictionariesResponse.ok) {
        dictionaries = await dictionariesResponse.json();
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
    await runSession(
        `/me/courses/${encodeURIComponent(id)}`,
        "Nothing to repeat right now.",
    );
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
    if (page === "login") initLogin();
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
