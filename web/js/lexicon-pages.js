import { fillLanguageSelect, formatCountdown, formatRate, identifierSpan, languageName, renderDefinitionList, strategyIconPrefix } from "./format.js";
import { setupCreateLexicon } from "./forms.js";
import { api, requireAuth } from "./api.js";

// Add-a-lexicon page.
//
// Lives on its own page (`new-lexicon.html`) with the form markup written
// directly in the HTML; this just wires it up.
export async function initNewLexicon() {
    requireAuth();
    await setupCreateLexicon(
        "add-lexicon-form",
        "add-lexicon-language",
        "add-status",
    );
}

// Lexicon list page.

export async function initLexicons() {
    requireAuth();

    const status = document.getElementById("status");
    const table = document.getElementById("lexicon-table");
    const rows = document.getElementById("lexicon-rows");
    const response = await api("/me/lexicons");
    const lexicons = await response.json();

    if (lexicons.length === 0) {
        status.textContent = "No lexicons yet.";
    } else {
        status.textContent = "";
        table.hidden = false;
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

        const languageCell = document.createElement("td");
        languageCell.textContent = languageName(lexicon.language);
        row.appendChild(languageCell);

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
            cell.style.textAlign = "right";
            row.appendChild(cell);
        }

        rows.appendChild(row);
    }
}

// Lexicon detail page.

export async function initLexicon() {
    requireAuth();

    const lexiconId = new URLSearchParams(location.search).get("lexicon");
    document
        .getElementById("lexicon-heading")
        .replaceChildren("Lexicon: ", identifierSpan(lexiconId));

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

    // "Check this lexicon": available unless the precision goal was just met
    // and rechecking is still paused (see `check_available`).
    const checkLink = document.getElementById("check-link");
    if (s.check_available) {
        checkLink.href = `check?lexicon=${encodeURIComponent(lexiconId)}`;
    } else {
        checkLink.removeAttribute("href");
        checkLink.textContent = s.recheck_available_at
            ? `Check available in ${formatCountdown(
                  new Date(s.recheck_available_at).getTime() - Date.now(),
              )}`
            : "Check this lexicon";
    }

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
        [
            "Selection",
            s.selection ? strategyIconPrefix(s.selection) + s.selection : "—",
            "strategy-text",
        ],
        ["Frequency list", s.frequency_list_name ?? "—"],
        ["Words checked", s.words],
        ["Known", s.known],
        ["Don't know", s.dont_know],
        [
            "Vocabulary rate",
            s.rate === null
                ? "not enough data"
                : formatRate(s.rate, s.sd, 2),
        ],
        [
            "Vocabulary rate (last 3 months)",
            s.trailing_rate === null
                ? "not enough recent data"
                : formatRate(s.trailing_rate, s.trailing_sd, 2),
        ],
        [
            "Precision goal (last 3 months)",
            s.achieved ? "Achieved" : "Not yet achieved",
        ],
    ];
    if (!s.check_available && s.recheck_available_at) {
        rows.push([
            "Next check available",
            formatCountdown(
                new Date(s.recheck_available_at).getTime() - Date.now(),
            ),
        ]);
    }
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

// Fill and wire the lexicon settings form: display name, identifier
// (renaming moves the URL, so the page redirects after), and translation
// targets (regenerate the dictionary/sentence config on save). Immutable
// identity (language, selection, frequency list) isn't shown here.
async function setupLexiconSettings(lexiconId) {
    const base = `/me/lexicons/${encodeURIComponent(lexiconId)}`;
    const section = document.getElementById("settings-section");
    const form = document.getElementById("settings-form");
    const nameInput = document.getElementById("setting-name");
    const idInput = document.getElementById("setting-id");
    const targets = document.getElementById("setting-targets");
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
            const heading = document.getElementById("lexicon-heading");
            if (saved.name) {
                heading.textContent = saved.name;
            } else {
                heading.replaceChildren(
                    "Lexicon: ",
                    identifierSpan(saved.lexicon_id),
                );
            }
            settingsStatus.textContent = "Saved.";
        } else {
            const { detail } = await result.json().catch(() => ({}));
            settingsStatus.textContent = detail || "Could not save settings.";
        }
    });
}
