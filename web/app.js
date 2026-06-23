"use strict";

// Minimal vanilla-JS client for the Emmio API. Holds the access token in
// localStorage and attaches it as a bearer token on each request. No build
// step, no framework; pages dispatch on `<body data-page="...">`.

const API = "/api/v1";
const TOKEN_KEY = "emmio_token";

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
        location.href = "login.html";
        throw new Error("Not authenticated");
    }
    return response;
}

function requireAuth() {
    if (!getToken()) location.href = "login.html";
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

// Login page.

function initLogin() {
    if (getToken()) {
        location.href = "index.html";
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
                location.href = "index.html";
            } else {
                error.textContent = "Incorrect email or password.";
            }
        });
}

// Registration page.

function initRegister() {
    if (getToken()) {
        location.href = "index.html";
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

function initHome() {
    requireAuth();
    document.getElementById("logout").addEventListener("click", () => {
        clearToken();
        location.href = "login.html";
    });
}

// Lexicon list page.

async function initLexicons() {
    requireAuth();

    document.getElementById("logout").addEventListener("click", () => {
        clearToken();
        location.href = "login.html";
    });

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
        link.href = `lexicon.html?lexicon=${encodeURIComponent(
            lexicon.lexicon_id,
        )}`;
        link.textContent = lexicon.lexicon_id;
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
        `check.html?lexicon=${encodeURIComponent(lexiconId)}`;

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

    const rows = [
        ["Language", languageName(s.language)],
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
    for (const [label, value] of rows) {
        const term = document.createElement("dt");
        term.textContent = label;
        const description = document.createElement("dd");
        description.textContent = value;
        stats.appendChild(term);
        stats.appendChild(description);
    }
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
    const lastAnswer = document.getElementById("last-answer");
    const sentence = document.getElementById("sentence");

    const queue = []; // Upcoming { word, lastResponse, lastTime, translation }.
    const history = []; // Answered { word } (most recent last), for undo.
    let current = null; // The item on screen.

    // Start loading a word's translation now so it's ready when needed. The
    // promise is stored on the item and awaited later (instant if resolved).
    function attachTranslation(item) {
        item.translation = api(
            `${base}/translation?word=${encodeURIComponent(item.word)}`,
        ).then((response) => (response.ok ? response.json() : null));
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
        for (const card of (await response.json()).words) {
            const item = {
                word: card.word,
                lastResponse: card.last_response,
                lastTime: card.last_time,
                sentence: card.sentence,
                translation: null,
            };
            attachTranslation(item);
            queue.push(item);
        }
    }

    function render() {
        translation.replaceChildren();
        undoBar.hidden = history.length === 0;
        if (history.length) {
            undoWord.textContent = history[history.length - 1].word;
        }
        renderLastAnswer();
        // The server returns a safe HTML fragment (text escaped, word in <b>).
        if (current && current.sentence) {
            sentence.innerHTML = current.sentence;
            sentence.hidden = false;
        } else {
            sentence.replaceChildren();
            sentence.hidden = true;
        }
        if (current) {
            word.textContent = current.word;
            status.textContent = "";
            answers.hidden = false;
        } else {
            word.textContent = "";
            answers.hidden = true;
            status.textContent = doneText;
        }
    }

    // Show what the user last answered for the current word, and when.
    function renderLastAnswer() {
        if (current && current.lastResponse) {
            const when = current.lastTime
                ? ` · ${relativeTime(current.lastTime)}`
                : "";
            lastAnswer.textContent =
                `Last answer: ${current.lastResponse}${when}`;
            lastAnswer.hidden = false;
        } else {
            lastAnswer.hidden = true;
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
        current = { word: undone, translation: null };
        attachTranslation(current);
        render();
    }

    async function showTranslation() {
        if (!current) return;
        translation.textContent = "Loading…";
        if (!current.translation) attachTranslation(current);
        const data = await current.translation;
        translation.replaceChildren();
        if (!data || data.dictionaries.length === 0) {
            translation.textContent = "No translation found.";
            return;
        }
        // One block per dictionary, with classes for future CSS styling.
        for (const entry of data.dictionaries) {
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
        if (button) {
            event.preventDefault();
            button.click();
        }
    });

    status.textContent = "Loading…";
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

    document.getElementById("logout").addEventListener("click", () => {
        clearToken();
        location.href = "login.html";
    });

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
        link.href = `course.html?course=${encodeURIComponent(
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
        `learn.html?course=${encodeURIComponent(courseId)}`;

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
    for (const [label, value] of rows) {
        const term = document.createElement("dt");
        term.textContent = label;
        const description = document.createElement("dd");
        description.textContent = value;
        stats.appendChild(term);
        stats.appendChild(description);
    }
}

// Dispatch on the page.

document.addEventListener("DOMContentLoaded", () => {
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
});
