import { identifierSpan, languageName, loadingDots } from "./format.js";
import { api, requireAuth } from "./api.js";

// Curated-list picker: one row per list, linking to
// `curated-list?language=<language>&list=<frequency_list_id>` — a curated
// list is addressed by that pair everywhere in this API (matching the
// schema's own `UNIQUE (language, frequency_list_id)` key and the CLI's
// `emmio curate <language> <frequency_list_id>`), never by a
// database-internal numeric id.

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
        link.href =
            `curated-list?language=${encodeURIComponent(item.language)}` +
            `&list=${encodeURIComponent(item.frequency_list_id)}`;
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

// Curated-list detail: a paginated table of every word in the list, with
// its current curation status — a read-only overview alongside the
// word-by-word `curate.html` flow, the same relationship `lexicon.html`
// (stats) has to `check.html` (the checking flow).

const WORDS_PAGE_SIZE = 100;

export async function initCuratedList() {
    requireAuth();

    const params = new URLSearchParams(location.search);
    const language = params.get("language");
    const frequencyListId = params.get("list");
    const base =
        `/curation/${encodeURIComponent(language)}` +
        `/${encodeURIComponent(frequencyListId)}`;

    document
        .getElementById("curated-list-heading")
        .replaceChildren(identifierSpan(frequencyListId));
    const curateUrl =
        `curate?language=${encodeURIComponent(language)}` +
        `&list=${encodeURIComponent(frequencyListId)}`;
    document
        .getElementById("curate-link")
        .addEventListener("click", () => {
            location.href = curateUrl;
        });

    // "(i)" toggles: show/hide the `.hint` paragraph describing what the
    // adjacent button does. `<a href="#">`, not a `<button>`, so the click
    // must stop the browser from actually navigating (scrolling to the top
    // and pushing a history entry).
    function wireInfoToggle(toggleId, infoId) {
        const toggle = document.getElementById(toggleId);
        const info = document.getElementById(infoId);
        toggle.addEventListener("click", (event) => {
            event.preventDefault();
            const shown = info.hidden;
            info.hidden = !shown;
            toggle.setAttribute("aria-expanded", String(shown));
        });
    }
    wireInfoToggle("curate-info-toggle", "curate-info");
    wireInfoToggle("auto-curate-info-toggle", "auto-curate-info");

    const status = document.getElementById("status");
    const table = document.getElementById("words-table");
    const rows = document.getElementById("words-rows");
    const pagination = document.getElementById("pagination");
    const pageIndicator = document.getElementById("page-indicator");
    const prevButton = document.getElementById("prev-page");
    const nextButton = document.getElementById("next-page");
    const autoCurateButton = document.getElementById("auto-curate");
    const autoCurateStatus = document.getElementById("auto-curate-status");

    let page = 1;

    async function loadPage() {
        status.textContent = "Loading…";
        const response = await api(
            `${base}/words?page=${page}&page_size=${WORDS_PAGE_SIZE}`,
        );
        if (!response.ok) {
            status.textContent = "Could not load words.";
            table.hidden = true;
            pagination.hidden = true;
            return;
        }
        const data = await response.json();

        rows.replaceChildren();
        for (const entry of data.words) {
            const row = document.createElement("tr");

            const wordCell = document.createElement("td");
            wordCell.textContent = entry.word;
            row.appendChild(wordCell);

            const strataCell = document.createElement("td");
            strataCell.textContent = entry.stratum;
            strataCell.style.textAlign = "right";
            row.appendChild(strataCell);

            const categoryCell = document.createElement("td");
            categoryCell.textContent = entry.category_label;
            row.appendChild(categoryCell);

            const votesCell = document.createElement("td");
            votesCell.textContent = entry.votes;
            votesCell.style.textAlign = "right";
            row.appendChild(votesCell);

            const agreementCell = document.createElement("td");
            agreementCell.textContent =
                entry.agreement == null
                    ? "—"
                    : `${Math.round(entry.agreement * 100)}%`;
            agreementCell.style.textAlign = "right";
            row.appendChild(agreementCell);

            rows.appendChild(row);
        }

        if (data.total === 0) {
            status.textContent = "No words in this list yet.";
            table.hidden = true;
            pagination.hidden = true;
            return;
        }
        status.textContent = "";
        table.hidden = false;

        const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));
        pageIndicator.textContent = `Page ${page} of ${totalPages} (${data.total} words)`;
        prevButton.disabled = page <= 1;
        nextButton.disabled = page >= totalPages;
        pagination.hidden = false;
    }

    prevButton.addEventListener("click", () => {
        if (page > 1) {
            page -= 1;
            void loadPage();
        }
    });
    nextButton.addEventListener("click", () => {
        page += 1;
        void loadPage();
    });

    // Each `/auto-curate` call is one server-side budget-capped pass (see
    // `_AUTO_CURATE_BUDGET`); repeat until a pass makes no further progress
    // (`resolved === 0`) rather than looping until `remaining` hits 0 —
    // some words have no automatic evidence either way and are left for a
    // human, so `remaining` can plateau above 0 forever. `MAX_PASSES` is
    // just a defensive cap against an unforeseen bug looping forever.
    const MAX_PASSES = 20;
    autoCurateButton.addEventListener("click", async () => {
        autoCurateButton.disabled = true;
        autoCurateStatus.hidden = false;
        let totalResolved = 0;
        let failed = false;
        for (let pass = 0; pass < MAX_PASSES; pass += 1) {
            autoCurateStatus.textContent =
                totalResolved > 0
                    ? `Auto-curated ${totalResolved} word(s) so far…`
                    : "Auto-curating…";
            const response = await api(`${base}/auto-curate`, {
                method: "POST",
            });
            if (!response.ok) {
                failed = true;
                break;
            }
            const result = await response.json();
            totalResolved += result.resolved;
            if (result.resolved === 0) {
                autoCurateStatus.textContent =
                    totalResolved > 0
                        ? `Auto-curated ${totalResolved} word(s). ` +
                          `${result.remaining} word(s) need a human.`
                        : `Nothing could be auto-curated — all ` +
                          `${result.remaining} remaining word(s) need a human.`;
                break;
            }
        }
        const stillRunning = autoCurateStatus.textContent.endsWith("…");
        if (failed) {
            autoCurateStatus.textContent = "Auto-curate failed.";
        } else if (totalResolved > 0 && stillRunning) {
            // Exited via MAX_PASSES rather than running dry: still useful
            // progress, worth a final summary instead of a stale "…" line.
            autoCurateStatus.textContent =
                `Auto-curated ${totalResolved} word(s) so far — ` +
                "click again for more.";
        }
        autoCurateButton.disabled = false;
        page = 1;
        await loadPage();
    });

    await loadPage();
}

// Curation session: the web equivalent of `emmio curate`. Unlike
// `check-session.js`, there is no prefetch queue (`/next` is a cheap query,
// not an expensive selector draw) and no undo (a curation vote is real
// history from the moment it lands, the same as `emmio curate`'s).

export async function initCurate() {
    requireAuth();

    const params = new URLSearchParams(location.search);
    const language = params.get("language");
    const frequencyListId = params.get("list");
    const base =
        `/curation/${encodeURIComponent(language)}` +
        `/${encodeURIComponent(frequencyListId)}`;
    document
        .getElementById("curated-list-heading")
        .replaceChildren(identifierSpan(frequencyListId));

    const word = document.getElementById("word");
    const sentence = document.getElementById("sentence");
    const translation = document.getElementById("translation");
    const answers = document.getElementById("answers");
    const status = document.getElementById("status");
    const sessionCounts = document.getElementById("session-counts");
    const externalLinks = document.getElementById("external-links");
    const googleLink = document.getElementById("google-link");
    const yandexLink = document.getElementById("yandex-link");
    const wiktionaryLink = document.getElementById("wiktionary-link");
    const kaikkiLink = document.getElementById("kaikki-link");

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
            `${base}/translation?word=${encodeURIComponent(forWord)}`,
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
            `${base}/sentence?word=${encodeURIComponent(forWord)}`,
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

    // Point the external lookup links (Google, Yandex, Wiktionary, Kaikki)
    // at the current word. Hidden when no word is showing. Mirrors
    // `check-session.js`'s `renderExternalLinks`.
    function renderExternalLinks() {
        if (!current) {
            externalLinks.hidden = true;
            return;
        }
        const forWord = encodeURIComponent(current.word);
        const langName = languageName(language);
        const query = `Translate ${langName} word "${current.word}".`;
        googleLink.href =
            `https://www.google.com/search?q=${encodeURIComponent(query)}`;
        yandexLink.href =
            `https://translate.yandex.ru/?source_lang=${encodeURIComponent(language)}` +
            `&target_lang=en&text=${forWord}`;
        // Wiktionary anchors the per-language section by its English name.
        wiktionaryLink.href =
            `https://en.wiktionary.org/wiki/${forWord}` +
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

    async function loadNext() {
        word.replaceChildren(loadingDots());
        sentence.replaceChildren();
        translation.replaceChildren();
        answers.hidden = true;
        status.textContent = "";

        const response = await api(`${base}/next`);
        const card = await response.json();
        if (!card.word) {
            current = null;
            word.textContent = "";
            status.textContent = "Nothing left to curate. Well done!";
            renderExternalLinks();
            return;
        }
        current = { word: card.word, stratum: card.stratum };
        word.textContent = card.word;
        answers.hidden = false;
        renderExternalLinks();
        void loadTranslation(card.word);
        void loadSentence(card.word);
    }

    async function answer(category) {
        if (!current || answering) return;
        answering = true;
        const answered = current.word;
        try {
            await api(`${base}/answer`, {
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
