import { identifierSpan, languageName, loadingDots } from "./format.js";
import { api, requireAuth } from "./api.js";

// Curated-list picker: one row per list, linking to `curate?id=<id>`.

export async function initCuratedLists() {
    requireAuth();

    const status = document.getElementById("status");
    const table = document.getElementById("curated-list-table");
    const rows = document.getElementById("curated-list-rows");
    const response = await api("/curation/lists");
    const lists = await response.json();

    if (lists.length === 0) {
        status.textContent = "No curated lists yet.";
    } else {
        status.textContent = "";
        table.hidden = false;
    }
    for (const item of lists) {
        const row = document.createElement("tr");

        const nameCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = `curate?id=${encodeURIComponent(item.curated_list_id)}`;
        link.textContent = item.name;
        nameCell.appendChild(link);
        row.appendChild(nameCell);

        const languageCell = document.createElement("td");
        languageCell.textContent = languageName(item.language);
        row.appendChild(languageCell);

        for (const value of [item.words, item.unvoted]) {
            const cell = document.createElement("td");
            cell.textContent = value;
            cell.style.textAlign = "right";
            row.appendChild(cell);
        }

        rows.appendChild(row);
    }
}

// Curation session: the web equivalent of `emmio curate`. Unlike
// `check-session.js`, there is no prefetch queue (`/next` is a cheap query,
// not an expensive selector draw) and no undo (a curation vote is real
// history from the moment it lands, the same as `emmio curate`'s).

export async function initCurate() {
    requireAuth();

    const id = new URLSearchParams(location.search).get("id");
    document
        .getElementById("curated-list-heading")
        .replaceChildren(identifierSpan(id));

    const word = document.getElementById("word");
    const sentence = document.getElementById("sentence");
    const translation = document.getElementById("translation");
    const answers = document.getElementById("answers");
    const status = document.getElementById("status");
    const sessionCounts = document.getElementById("session-counts");

    let current = null; // { word, stratum } of the word on screen.
    let answering = false; // Guards a second click landing before advance().
    let curatedCount = 0;

    // Render the category buttons once, from the server's own list — so the
    // taxonomy only has to change in one place (`emmio/lexicon/core.py`'s
    // `NOT_TO_CHECK_CATEGORIES`) to show up here too.
    const categoriesResponse = await api("/curation/categories");
    for (const option of await categoriesResponse.json()) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = option.label;
        button.addEventListener("click", () => answer(option.code));
        answers.appendChild(button);
    }

    function renderStatus() {
        sessionCounts.hidden = curatedCount === 0;
        sessionCounts.textContent = `Curated: ${curatedCount}`;
    }

    // The translation and example sentence are fetched separately from the
    // word itself (like the check page's), so a slow Tatoeba/Kaikki lookup
    // never delays showing the word. `current` is checked before rendering
    // in case the curator already answered and moved on by the time a slow
    // request resolves.
    async function loadTranslation(forWord) {
        const response = await api(
            `/curation/${encodeURIComponent(id)}/translation` +
                `?word=${encodeURIComponent(forWord)}`,
        );
        if (!response.ok || current?.word !== forWord) return;
        const data = await response.json();
        if (current?.word !== forWord) return;
        translation.replaceChildren();
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
            translation.appendChild(block);
        }
    }

    async function loadSentence(forWord) {
        const response = await api(
            `/curation/${encodeURIComponent(id)}/sentence` +
                `?word=${encodeURIComponent(forWord)}`,
        );
        if (!response.ok || current?.word !== forWord) return;
        const data = await response.json();
        if (current?.word !== forWord) return;
        sentence.replaceChildren();
        if (data.sentence) {
            const span = document.createElement("span");
            span.innerHTML = data.sentence; // Safe HTML fragment.
            sentence.appendChild(span);
        }
    }

    async function loadNext() {
        word.replaceChildren(loadingDots());
        sentence.replaceChildren();
        translation.replaceChildren();
        answers.hidden = true;
        status.textContent = "";

        const response = await api(`/curation/${encodeURIComponent(id)}/next`);
        const card = await response.json();
        if (!card.word) {
            current = null;
            word.textContent = "";
            status.textContent = "Nothing left to curate. Well done!";
            return;
        }
        current = { word: card.word, stratum: card.stratum };
        word.textContent = card.word;
        answers.hidden = false;
        void loadTranslation(card.word);
        void loadSentence(card.word);
    }

    async function answer(category) {
        if (!current || answering) return;
        answering = true;
        const answered = current.word;
        try {
            await api(`/curation/${encodeURIComponent(id)}/answer`, {
                method: "POST",
                body: { word: answered, category },
            });
            curatedCount += 1;
            renderStatus();
            await loadNext();
        } finally {
            answering = false;
        }
    }

    renderStatus();
    await loadNext();
}
