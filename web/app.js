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
    const list = document.getElementById("lexicon-list");
    const response = await api("/me/lexicons");
    const lexicons = await response.json();

    if (lexicons.length === 0) {
        status.textContent = "No lexicons yet.";
        return;
    }
    status.textContent = "";
    for (const lexicon of lexicons) {
        const item = document.createElement("li");

        const link = document.createElement("a");
        link.href = `check.html?lexicon=${encodeURIComponent(
            lexicon.lexicon_id,
        )}`;
        link.textContent = `${lexicon.lexicon_id} (${lexicon.language})`;
        item.appendChild(link);

        // Short info: selection strategy and number of words checked.
        const info = document.createElement("small");
        const parts = [];
        if (lexicon.selection) parts.push(lexicon.selection);
        parts.push(`${lexicon.words} words`);
        info.textContent = ` — ${parts.join(", ")}`;
        item.appendChild(info);

        list.appendChild(item);
    }
}

// Lexicon checking page.

async function initCheck() {
    requireAuth();

    const lexiconId = new URLSearchParams(location.search).get("lexicon");
    const word = document.getElementById("word");
    const status = document.getElementById("status");
    const answers = document.getElementById("answers");
    const translation = document.getElementById("translation");

    document.getElementById("lexicon-heading").textContent =
        `Check lexicon: ${lexiconId}`;

    async function loadNext() {
        word.textContent = "";
        translation.textContent = "";
        status.textContent = "Loading…";
        answers.hidden = true;

        const response = await api(
            `/me/lexicons/${encodeURIComponent(lexiconId)}/next`,
        );
        if (!response.ok) {
            const { detail } = await response.json().catch(() => ({}));
            status.textContent = detail || "Could not load the next word.";
            return;
        }
        const next = await response.json();
        if (!next.word) {
            status.textContent = "No more words to check.";
            return;
        }
        word.textContent = next.word;
        status.textContent = "";
        answers.hidden = false;
    }

    async function answer(response) {
        const current = word.textContent;
        if (!current) return;
        await api(`/me/lexicons/${encodeURIComponent(lexiconId)}/answer`, {
            method: "POST",
            body: { word: current, response },
        });
        await loadNext();
    }

    async function showTranslation() {
        const current = word.textContent;
        if (!current) return;
        translation.textContent = "Loading…";
        const response = await api(
            `/me/lexicons/${encodeURIComponent(lexiconId)}/translation` +
                `?word=${encodeURIComponent(current)}`,
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
            answer(button.dataset.response),
        );
    }
    document
        .getElementById("show-translation")
        .addEventListener("click", showTranslation);

    await loadNext();
}

// Dispatch on the page.

document.addEventListener("DOMContentLoaded", () => {
    const page = document.body.dataset.page;
    if (page === "login") initLogin();
    else if (page === "lexicons") initLexicons();
    else if (page === "check") initCheck();
});
