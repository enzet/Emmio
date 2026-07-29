import { createLanguageHistoryChart } from "./charts.js";
import { emmioLevel, formatRate, identifierSpan, languageName, strategyIconPrefix } from "./format.js";
import { api, requireAuth } from "./api.js";

// Home / dashboard page.

export async function initHome() {
    requireAuth();

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

    // Set once the history chart exists (it needs the history fetch below),
    // so a row's hover listener — wired up now, while rows first render —
    // can still reach it later.
    let chart = null;

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

        // Lexicon column: a link to the main lexicon plus check-availability;
        // filled in once the rate estimate arrives below.
        const lexiconCell = document.createElement("td");
        row.appendChild(lexiconCell);

        if (summary) {
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

    // Languages with a main lexicon first (re-sorted by rate once it
    // arrives), then course-only ones alphabetically. `sectionEnd` marks the
    // boundary so rated rows can be moved before it without disturbing the rest.
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
