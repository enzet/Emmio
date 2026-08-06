import { identifierSpan, relativeTime } from "./format.js";
import { api, requireAuth } from "./api.js";

// Dedicated lexicon word-list page: a paginated table filtered to "All",
// "Know", or "Don't know" (matching `get_lexicon_stats`'s own grouping),
// reached from the lexicon page's stats rows via `?lexicon=<id>&response=
// <filter>`. Switching filters re-fetches in place (no page reload); the
// query string is kept in sync via `history.replaceState` so the URL stays
// shareable/bookmarkable.

const PAGE_SIZE = 100;
const VALID_RESPONSES = new Set(["all", "know", "dont"]);

export async function initLexiconWords() {
    requireAuth();

    const params = new URLSearchParams(location.search);
    const lexiconId = params.get("lexicon");
    let response = params.get("response");
    if (!VALID_RESPONSES.has(response)) response = "all";

    document.getElementById("back-link").href =
        `lexicon?lexicon=${encodeURIComponent(lexiconId)}`;
    document
        .getElementById("words-heading")
        .replaceChildren("Words: ", identifierSpan(lexiconId));

    const base = `/me/lexicons/${encodeURIComponent(lexiconId)}/words`;
    const status = document.getElementById("status");
    const table = document.getElementById("words-table");
    const rows = document.getElementById("words-rows");
    const wordsStatus = document.getElementById("words-status");
    const pagination = document.getElementById("pagination");
    const pageIndicator = document.getElementById("page-indicator");
    const prevButton = document.getElementById("prev-page");
    const nextButton = document.getElementById("next-page");
    const filterButtons = document.querySelectorAll("#filter-tabs button");

    let page = 1;

    function updateFilterButtons() {
        for (const button of filterButtons) {
            button.setAttribute(
                "aria-pressed",
                String(button.dataset.response === response),
            );
        }
    }

    async function loadPage() {
        wordsStatus.textContent = "Loading…";
        const result = await api(
            `${base}?response=${response}&page=${page}` +
                `&page_size=${PAGE_SIZE}`,
        );
        if (!result.ok) {
            wordsStatus.textContent = "Could not load words.";
            table.hidden = true;
            pagination.hidden = true;
            return;
        }
        const data = await result.json();

        rows.replaceChildren();
        for (const entry of data.words) {
            const row = document.createElement("tr");

            const wordCell = document.createElement("td");
            wordCell.textContent = entry.word;
            row.appendChild(wordCell);

            const responseCell = document.createElement("td");
            responseCell.textContent = entry.response_label ?? "—";
            row.appendChild(responseCell);

            const lastSeenCell = document.createElement("td");
            lastSeenCell.textContent = entry.last_seen
                ? relativeTime(entry.last_seen)
                : "—";
            row.appendChild(lastSeenCell);

            rows.appendChild(row);
        }

        if (data.total === 0) {
            wordsStatus.textContent = "No words.";
            table.hidden = true;
            pagination.hidden = true;
            return;
        }
        wordsStatus.textContent = "";
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

    for (const button of filterButtons) {
        button.addEventListener("click", () => {
            if (button.dataset.response === response) return;
            response = button.dataset.response;
            page = 1;
            updateFilterButtons();
            const url = new URL(location.href);
            url.searchParams.set("response", response);
            history.replaceState(null, "", url);
            void loadPage();
        });
    }

    updateFilterButtons();
    status.textContent = "";
    await loadPage();
}
