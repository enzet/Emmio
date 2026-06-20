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
        location.href = "index.html";
        throw new Error("Not authenticated");
    }
    return response;
}

function requireAuth() {
    if (!getToken()) location.href = "index.html";
}

// Login/register page.

function initLogin() {
    if (getToken()) {
        location.href = "lexicons.html";
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
                },
            });
            if (response.ok) {
                const { access_token } = await response.json();
                setToken(access_token);
                location.href = "lexicons.html";
            } else {
                error.textContent = "Incorrect email or password.";
            }
        });

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

// Lexicon list page.

async function initLexicons() {
    requireAuth();

    document.getElementById("logout").addEventListener("click", () => {
        clearToken();
        location.href = "index.html";
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
            lexicon.language,
            lexicon.selection || "",
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
        ["Language", s.language],
        ["Selection", s.selection || "—"],
        ["Words checked", s.words],
        ["Known", s.known],
        ["Don't know", s.dont_know],
        [
            "Vocabulary rate",
            s.rate === null ? "not enough data" : s.rate.toFixed(1),
        ],
        ["Precision (total don't-know answers)", s.precision],
        ["Don't know (last 7 days)", s.dont_last_week],
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

// Session pages: lexicon checking and learning repetition share one flow —
// fetch the next word, optionally reveal a translation, record an answer, and
// move on. `base` is the resource path, e.g. `/me/lexicons/fr`.

async function runSession(base, doneText) {
    const word = document.getElementById("word");
    const status = document.getElementById("status");
    const answers = document.getElementById("answers");
    const translation = document.getElementById("translation");

    async function loadNext() {
        word.textContent = "";
        translation.textContent = "";
        status.textContent = "Loading…";
        answers.hidden = true;

        const response = await api(`${base}/next`);
        if (!response.ok) {
            const { detail } = await response.json().catch(() => ({}));
            status.textContent = detail || "Could not load the next word.";
            return;
        }
        const next = await response.json();
        if (!next.word) {
            status.textContent = doneText;
            return;
        }
        word.textContent = next.word;
        status.textContent = "";
        answers.hidden = false;
    }

    async function answer(response, toSkip = false) {
        const current = word.textContent;
        if (!current) return;
        await api(`${base}/answer`, {
            method: "POST",
            body: { word: current, response, to_skip: toSkip },
        });
        await loadNext();
    }

    async function showTranslation() {
        const current = word.textContent;
        if (!current) return;
        translation.textContent = "Loading…";
        const response = await api(
            `${base}/translation?word=${encodeURIComponent(current)}`,
        );
        if (response.ok) {
            const data = await response.json();
            // The server returns a safe HTML fragment (text escaped, fixed
            // tags) or null.
            if (data.translation) {
                translation.innerHTML = data.translation;
            } else {
                translation.textContent = "No translation found.";
            }
        } else {
            translation.textContent = "Could not load translation.";
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

    await loadNext();
}

// Lexicon checking page.

async function initCheck() {
    requireAuth();
    const id = new URLSearchParams(location.search).get("lexicon");
    document.getElementById("lexicon-heading").textContent =
        `Check lexicon: ${id}`;
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
        location.href = "index.html";
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
            course.learning_language,
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
        ["Language", s.learning_language],
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
    else if (page === "lexicons") initLexicons();
    else if (page === "lexicon") initLexicon();
    else if (page === "check") initCheck();
    else if (page === "courses") initCourses();
    else if (page === "course") initCourse();
    else if (page === "learn") initLearn();
});
