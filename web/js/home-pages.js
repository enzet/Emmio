import { createLanguageHistoryChart } from "./charts.js";
import { emmioLevel, fillLanguageSelect, formatRate, identifierSpan, languageName, strategyIconPrefix } from "./format.js";
import { api, requireAuth } from "./api.js";
import { initLanguageEstimates, loadKnowledgeKinds, setupEstimateFields } from "./language-knowledge.js";

// Home / dashboard page.

// The dashboard's Courses section: every course, whatever language it names
// (or none). A course with no learnings yet offers to add one directly,
// since an empty course is a dead end otherwise.
function renderCourses(courses) {
    const status = document.getElementById("courses-status");
    const table = document.getElementById("course-table");
    const rows = document.getElementById("course-rows");

    status.textContent = courses.length === 0 ? "No courses yet." : "";
    table.hidden = courses.length === 0;

    for (const course of courses) {
        const row = document.createElement("tr");

        const nameCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = `course?course=${encodeURIComponent(course.course_id)}`;
        link.textContent = course.name;
        nameCell.appendChild(link);
        row.appendChild(nameCell);

        const languageCell = document.createElement("td");
        languageCell.textContent = languageName(course.language);
        row.appendChild(languageCell);

        const learningsCell = document.createElement("td");
        if (course.learning_count > 0) {
            learningsCell.textContent = course.learning_count;
        } else {
            const add = document.createElement("a");
            add.href = `new-learning?course=${encodeURIComponent(
                course.course_id,
            )}`;
            add.textContent = "+ add a learning";
            learningsCell.appendChild(add);
        }
        row.appendChild(learningsCell);

        rows.appendChild(row);
    }
}

export async function initHome() {
    requireAuth();

    document
        .getElementById("add-language-button")
        .addEventListener("click", () => {
            location.href = "new-language";
        });
    document
        .getElementById("add-course-button")
        .addEventListener("click", () => {
            location.href = "new-course";
        });

    const status = document.getElementById("languages-status");
    const table = document.getElementById("languages-table");
    const rows = document.getElementById("languages-rows");

    // `/me/languages` estimates every main lexicon's rate (up to a second
    // each on a cache miss) — too slow to block the first paint on. Fetch
    // the cheap `/me/languages/summary` + courses first, render placeholders,
    // and fill in the real rate once `/me/languages` resolves below.
    const [summaryResponse, coursesResponse] = await Promise.all([
        api("/me/languages/summary"),
        api("/me/courses"),
    ]);
    const summaries = summaryResponse.ok ? await summaryResponse.json() : [];
    const courses = coursesResponse.ok ? await coursesResponse.json() : [];
    // Courses have their own section: they are a sibling of languages, not
    // something a language contains, so they are listed in full rather than
    // grouped under the languages they happen to name.
    renderCourses(courses);

    // Nothing yet: welcome the user and offer to add their first language.
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

    // Set once the history chart exists (it needs the history fetch below),
    // so a row's hover listener — wired up now, while rows first render —
    // can still reach it later.
    let chart = null;

    // Render one language row from its `/me/languages/summary` entry.
    function renderLanguageRow(language, summary) {
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

        // A language object exists as soon as the user has anything in the
        // language, so it may well have no main lexicon (and thus no rate):
        // a language they have only self-reported a level for still shows up.
        const hasLexicon = Boolean(summary && summary.lexicon_id);

        const rateCell = document.createElement("td");
        rateCell.textContent = hasLexicon ? "…" : "—";
        rateCell.style.fontVariantNumeric = "tabular-nums";
        rateCell.style.textAlign = "right";
        row.appendChild(rateCell);

        // Emmio-specific language level, derived from the rate once it
        // arrives.
        const levelCell = document.createElement("td");
        levelCell.textContent = hasLexicon ? "…" : "—";
        levelCell.style.fontVariantNumeric = "tabular-nums";
        levelCell.style.textAlign = "right";
        row.appendChild(levelCell);

        // The level the user reported by hand (newest estimate), alongside
        // the computed one — the two are independent, neither derives from
        // the other.
        const selfReportedCell = document.createElement("td");
        const selfReported = summary && summary.self_reported;
        if (selfReported) {
            const label = selfReported.caption || selfReported.kind_label;
            selfReportedCell.appendChild(
                document.createTextNode(
                    selfReported.value ? `${selfReported.value} ` : "",
                ),
            );
            const kind = document.createElement("span");
            kind.className = "knowledge-kind";
            kind.textContent = selfReported.value ? `(${label})` : label;
            selfReportedCell.appendChild(kind);
        } else {
            selfReportedCell.textContent = "—";
        }
        row.appendChild(selfReportedCell);

        // Lexicon column: a link to the main lexicon plus check-availability;
        // filled in once the rate estimate arrives below.
        const lexiconCell = document.createElement("td");
        row.appendChild(lexiconCell);

        if (hasLexicon) {
            pendingCells.set(language, { rateCell, levelCell, lexiconCell });
            // Sync with the history chart: hovering this row highlights its
            // line there, and (wired the other way, in the chart itself)
            // hovering its line here highlights this row.
            row.addEventListener("mouseenter", () => {
                if (chart) chart.highlight(language);
            });
            row.addEventListener("mouseleave", () => {
                if (chart) chart.highlight(null);
            });
        }

        rows.appendChild(row);
        return row;
    }

    // Languages with a main lexicon first (re-sorted by rate once it
    // arrives), then the rateless ones alphabetically. `sectionEnd` marks the
    // boundary so rated rows can be moved before it without disturbing the rest.
    const rated = new Set();
    const ratedRows = new Map();
    for (const summary of summaries) {
        if (!summary.lexicon_id) continue;
        rated.add(summary.language);
        ratedRows.set(
            summary.language,
            renderLanguageRow(summary.language, summary),
        );
    }
    const sectionEnd = document.createComment("rateless");
    rows.appendChild(sectionEnd);
    // Languages with no main lexicon, and so no rate to sort by: their only
    // content is a self-reported level, a learning, or a non-main lexicon.
    for (const summary of summaries
        .filter((entry) => !rated.has(entry.language))
        .sort((a, b) =>
            languageName(a.language).localeCompare(languageName(b.language)),
        )) {
        renderLanguageRow(summary.language, summary);
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
    // convergence chart, rather than a server-rendered image. The
    // month/year buttons above the chart re-fetch at the chosen grid
    // spacing (the resampling itself is server-side, `_grid_points`).
    const intervalButtons = document.querySelectorAll(
        "#lexicon-history-interval button",
    );

    async function loadHistory(interval) {
        const historyResponse = await api(
            `/me/lexicons/history?interval=${interval}`,
        );
        if (!historyResponse.ok) return;
        if (!chart) {
            chart = createLanguageHistoryChart(
                document.getElementById("lexicon-history"),
                document.getElementById("lexicon-history-svg"),
                document.getElementById("lexicon-history-tooltip"),
                (language) => {
                    for (const row of ratedRows.values()) {
                        row.classList.remove("row-highlighted");
                    }
                    const row = language && ratedRows.get(language);
                    if (row) row.classList.add("row-highlighted");
                },
            );
        }
        chart.setData(await historyResponse.json(), interval);
    }

    for (const button of intervalButtons) {
        button.addEventListener("click", () => {
            if (button.getAttribute("aria-pressed") === "true") return;
            for (const other of intervalButtons) {
                other.setAttribute("aria-pressed", String(other === button));
            }
            loadHistory(button.dataset.interval);
        });
    }

    await loadHistory("month");
}

// Language page: every lexicon and course for one language, gathered in one
// place. The dashboard links each language name here instead of listing
// everything inline.
export async function initLanguage() {
    requireAuth();

    const language = new URLSearchParams(location.search).get("language");
    document.getElementById("language-heading").textContent =
        `Language: ${languageName(language)}`;
    document
        .getElementById("add-lexicon-link")
        .addEventListener("click", () => {
            location.href = `new-lexicon?language=${encodeURIComponent(language)}`;
        });
    document
        .getElementById("add-course-link")
        .addEventListener("click", () => {
            location.href = "new-course";
        });

    // Self-reported estimates for this language, in their own module (the
    // form is a small state machine over the assessment-kind taxonomy).
    initLanguageEstimates(language);

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

// "Add a language" page. The server creates the language, a default lexicon
// over its curated list, and the starting estimate in one go, so this form
// collects the language plus that estimate (see `create_my_language`).

export async function initNewLanguage() {
    requireAuth();

    const form = document.getElementById("add-language-form");
    const select = document.getElementById("add-language-language");
    const status = document.getElementById("add-language-status");
    const submit = form.querySelector('button[type="submit"]');

    // Only languages that can still be added: one the user already has, or
    // one with no curated list behind it, would be rejected on submit.
    const [languagesResponse, kinds] = await Promise.all([
        api("/me/languages/available"),
        loadKnowledgeKinds(),
    ]);
    if (!languagesResponse.ok || kinds === null) {
        status.textContent = "Could not load languages or assessment kinds.";
        return;
    }
    const available = await languagesResponse.json();
    if (available.length === 0) {
        status.textContent =
            "You have already added every language Emmio has a curated word " +
            "list for.";
        submit.disabled = true;
        return;
    }
    fillLanguageSelect(select, available);

    const fields = setupEstimateFields(kinds, select.value);
    select.addEventListener("change", () => fields.setLanguage(select.value));

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        status.textContent = "Adding…";
        const result = await api("/me/languages", {
            method: "POST",
            body: { language: select.value, ...fields.collect() },
        });
        if (result.ok) {
            // Straight to the new language's own page, where its lexicon is
            // waiting and further estimates are added.
            location.href = `language?language=${encodeURIComponent(
                select.value,
            )}`;
        } else {
            const { detail } = await result.json().catch(() => ({}));
            status.textContent = detail || "Could not add language.";
        }
    });
}
