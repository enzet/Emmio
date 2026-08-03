import { fillLanguageSelect, languageName, strategyIconPrefix } from "./format.js";
import { api } from "./api.js";

// Skin a native strategy <select> with a decorative icon+label overlay:
// <option> text stays icon-free since macOS Safari/Chrome render the open
// list as a native popup that can't show the icon font's private-use glyphs,
// but the closed box (drawn by the page) can — so the overlay covers just
// that. It's `aria-hidden`/`pointer-events: none`; the real <select> still
// drives interaction, focus, and the accessible name.
function addStrategyOverlay(select) {
    const wrapper = document.createElement("span");
    wrapper.className = "strategy-picker";
    select.replaceWith(wrapper);
    wrapper.appendChild(select);

    const overlay = document.createElement("span");
    overlay.className = "strategy-picker-overlay strategy-text";
    overlay.setAttribute("aria-hidden", "true");
    wrapper.appendChild(overlay);

    // Match the select's own (usually smaller) control font, not the page's
    // ambient font the overlay would otherwise inherit.
    const selectStyle = getComputedStyle(select);
    overlay.style.fontSize = selectStyle.fontSize;
    overlay.style.lineHeight = selectStyle.lineHeight;

    function update() {
        const option = select.options[select.selectedIndex];
        overlay.textContent = option
            ? strategyIconPrefix(option.value) + option.textContent
            : "";
    }

    // The select auto-sizes to its icon-free option text, which can be too
    // narrow for the icon-prefixed overlay; measure the worst case and widen.
    let maxTextWidth = 0;
    for (const option of select.options) {
        overlay.textContent = strategyIconPrefix(option.value) + option.textContent;
        maxTextWidth = Math.max(maxTextWidth, overlay.scrollWidth);
    }
    const overlayStyle = getComputedStyle(overlay);
    const needed =
        maxTextWidth + parseFloat(overlayStyle.left) + parseFloat(overlayStyle.right);
    const shortfall = needed - select.getBoundingClientRect().width;
    if (shortfall > 0) {
        select.style.paddingLeft = `calc(${selectStyle.paddingLeft} + ${Math.ceil(shortfall) + 2}px)`;
    }

    select.addEventListener("change", update);
    update();
}

// Wire up a "create lexicon" form: fill the language/frequency-list/strategy
// pickers, and on submit create the lexicon (set as main) and open it.
export async function setupCreateLexicon(formId, selectId, statusId) {
    const form = document.getElementById(formId);
    const select = document.getElementById(selectId);
    const frequencyListSelect = form.querySelector(".lexicon-frequency-list");
    const targets = form.querySelector(".translation-languages");
    const selection = form.querySelector(".lexicon-selection");
    const createStatus = document.getElementById(statusId);

    const [response, frequencyListResponse, targetResponse, strategyResponse] =
        await Promise.all([
            api("/lexicon-languages"),
            api("/frequency-lists"),
            api("/translation-languages"),
            api("/lexicon-strategies"),
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

    // Arriving from a language page preselects that language, rather than
    // making the user pick it again from scratch.
    const linkedLanguage = new URLSearchParams(location.search).get(
        "language",
    );
    fillLanguageSelect(
        select,
        available,
        available.some((entry) => entry.language === linkedLanguage)
            ? linkedLanguage
            : undefined,
    );

    const frequencyLists = await frequencyListResponse.json();
    const listOptions = { includeCurated: true };
    fillFrequencyListSelect(
        frequencyListSelect,
        frequencyLists,
        select.value,
        listOptions,
    );
    select.addEventListener("change", () => {
        fillFrequencyListSelect(
            frequencyListSelect,
            frequencyLists,
            select.value,
            listOptions,
        );
        updateSelectionLock();
    });

    // Fill the "translate into" picker with every known language; preselect
    // English as the most common target.
    fillLanguageSelect(targets, await targetResponse.json(), "en");

    // Fill the selection-strategy picker from the server's single source of
    // truth; the first strategy (frequency-weighted random) is the default.
    for (const strategy of await strategyResponse.json()) {
        const option = document.createElement("option");
        option.value = strategy.value;
        option.textContent = strategy.label;
        selection.appendChild(option);
    }
    addStrategyOverlay(selection);

    // A curated list is a small, fixed, pre-reviewed panel, not a rankable
    // full list — only `stratified` (SFWR) knows how to draw from one (see
    // `CuratedStratifiedSelector`), so picking one locks the strategy.
    function updateSelectionLock() {
        const chosen = frequencyListSelect.selectedOptions[0];
        const curated = chosen?.dataset.curated === "1";
        selection.disabled = curated;
        if (curated && selection.value !== "stratified") {
            selection.value = "stratified";
            selection.dispatchEvent(new Event("change"));
        }
    }
    frequencyListSelect.addEventListener("change", updateSelectionLock);
    updateSelectionLock();

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
                selection: selection.value,
                frequency_list: decodeFrequencyListValue(
                    frequencyListSelect.value,
                ),
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

// A frequency-list option is identified by `id` plus `year` (only
// `frequency_words` options need the year, to tell cached releases apart)
// plus whether it draws from a curated panel rather than the raw list (a
// language may offer both under the same id/year, see
// `FrequencyListOption.curated`) — encode all three into the <select> value
// as a single string.
function encodeFrequencyListValue(option) {
    return `${option.id}::${option.year ?? ""}::${option.curated ? "1" : ""}`;
}

function decodeFrequencyListValue(value) {
    const [id, year, curated] = value.split("::");
    return { id, year: year ? Number(year) : null, curated: curated === "1" };
}

// Fill the "draw new words from" picker with `language`'s frequency lists,
// starring and preselecting the default one. Re-called whenever the
// lexicon's/learning's language changes. Curated options are opt-in
// (`includeCurated`): only a lexicon's own selection strategy knows how to
// draw from one (`CuratedStratifiedSelector`), so a learning's picker never
// offers them, to avoid silently promising curated-only words it can't
// deliver.
function fillFrequencyListSelect(
    select,
    frequencyLists,
    language,
    { includeCurated = false } = {},
) {
    select.innerHTML = "";
    for (const option of frequencyLists) {
        if (option.language !== language) continue;
        if (option.curated && !includeCurated) continue;
        const el = document.createElement("option");
        el.value = encodeFrequencyListValue(option);
        el.textContent = (option.is_default ? "★ " : "") + option.name;
        el.dataset.curated = option.curated ? "1" : "";
        if (option.is_default) el.selected = true;
        select.appendChild(el);
    }
}

// Fill a learning's lexicon picker ("skip known words" or "ask about unseen
// words") with the caller's lexicons for `language`, plus a leading "none".
export function fillLearningLexiconSelect(select, lexicons, language, selected) {
    select.innerHTML = "";
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "(none)";
    if (!selected) none.selected = true;
    select.appendChild(none);
    for (const lexicon of lexicons) {
        if (lexicon.language !== language) continue;
        const option = document.createElement("option");
        option.value = lexicon.lexicon_id;
        option.textContent =
            (lexicon.is_main ? "★ " : "") +
            (lexicon.name || lexicon.lexicon_id);
        if (lexicon.lexicon_id === selected) option.selected = true;
        select.appendChild(option);
    }
}

// Render a "question types" checkbox group: one per server-supported type,
// checked per `checkedTypes` (a `Set` of values).
export function renderQuestionTypeCheckboxes(
    container,
    idPrefix,
    types,
    checkedTypes,
) {
    container.innerHTML = "";
    for (const type of types) {
        const label = document.createElement("label");
        label.className = "checkbox";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.id = `${idPrefix}-${type.value}`;
        input.value = type.value;
        input.checked = checkedTypes.has(type.value);
        label.appendChild(input);
        label.appendChild(document.createTextNode(` ${type.label}`));
        container.appendChild(label);
    }
}

// Read back which question types are checked in a group rendered above.
export function checkedQuestionTypes(container) {
    return Array.from(
        container.querySelectorAll("input[type=checkbox]:checked"),
        (input) => input.value,
    );
}

// Wire up an "add a course" form: just a language and a name. Languages
// offered are the union of word-learning and symbol-learning support, so
// every one can host at least one learning afterward. On submit, creates the
// course and opens its (empty) detail page.
export async function setupCreateCourse(formId, selectId, statusId) {
    const form = document.getElementById(formId);
    const select = document.getElementById(selectId);
    const nameInput = form.querySelector(".course-name");
    const submitButton = form.querySelector("button[type=submit]");
    const createStatus = document.getElementById(statusId);

    const [wordLanguageResponse, alphabetLanguageResponse] =
        await Promise.all([
            api("/lexicon-languages"),
            api("/alphabet-languages"),
        ]);
    const byLanguage = new Map();
    for (const entry of await wordLanguageResponse.json()) {
        byLanguage.set(entry.language, entry);
    }
    for (const entry of await alphabetLanguageResponse.json()) {
        if (!byLanguage.has(entry.language)) byLanguage.set(entry.language, entry);
    }
    const available = [...byLanguage.values()];

    if (available.length === 0) {
        createStatus.textContent = "No languages are available yet.";
        select.disabled = true;
        submitButton.disabled = true;
        return;
    }
    fillLanguageSelect(select, available);

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        createStatus.textContent = "Creating…";
        const result = await api("/me/courses", {
            method: "POST",
            body: {
                language: select.value,
                name: nameInput.value.trim() || languageName(select.value),
            },
        });
        if (result.ok) {
            const { course_id } = await result.json();
            location.href = `course?course=${encodeURIComponent(course_id)}`;
        } else {
            const { detail } = await result.json().catch(() => ({}));
            createStatus.textContent = detail || "Could not create course.";
        }
    });
}

// Wire up an "add a learning" form for an existing course. A `word` learning
// (the default) draws from a frequency list and needs translation targets; a
// `symbol` learning drills the alphabet and needs none of that — the "What
// to learn" radio toggles the word-only fields, offered only if the course's
// language actually supports that type. On submit, opens the learning session.
export async function setupCreateLearning(courseId, formId, statusId) {
    const form = document.getElementById(formId);
    const createStatus = document.getElementById(statusId);
    const courseResponse = await api(
        `/me/courses/${encodeURIComponent(courseId)}`,
    );
    if (!courseResponse.ok) {
        createStatus.textContent = "Unknown course.";
        form.hidden = true;
        return;
    }
    const course = await courseResponse.json();
    document.getElementById("add-learning-heading").textContent =
        `Add a learning: ${course.name}`;

    const learningTypeInputs = Array.from(
        form.querySelectorAll(".learning-type"),
    );
    const wordFields = form.querySelector(".learning-word-fields");
    const targets = form.querySelector(".translation-languages");
    const frequencyListSelect = form.querySelector(
        ".learning-frequency-list",
    );
    const lexiconSelect = form.querySelector(".learning-lexicon");
    const askLexiconSelect = form.querySelector(".learning-ask-lexicon");
    const nameInput = form.querySelector(".learning-name");
    const maxForDayInput = form.querySelector(".learning-max-for-day");
    const playAudioInput = form.querySelector(".learning-play-audio");
    const questionTypesContainer = form.querySelector(
        ".learning-question-types",
    );
    const submitButton = form.querySelector("button[type=submit]");

    const [
        wordLanguageResponse,
        alphabetLanguageResponse,
        targetResponse,
        frequencyListResponse,
        lexiconResponse,
        questionTypeResponse,
    ] = await Promise.all([
        api("/lexicon-languages"),
        api("/alphabet-languages"),
        api("/translation-languages"),
        api("/frequency-lists"),
        api("/me/lexicons"),
        api("/question-types"),
    ]);
    const supportsWord = (await wordLanguageResponse.json()).some(
        (entry) => entry.language === course.language,
    );
    const supportsSymbol = (await alphabetLanguageResponse.json()).some(
        (entry) => entry.language === course.language,
    );

    fillLanguageSelect(targets, await targetResponse.json(), "en");

    // Every question type is allowed unless the user narrows it down.
    const questionTypes = await questionTypeResponse.json();
    renderQuestionTypeCheckboxes(
        questionTypesContainer,
        "add-learning-question-type",
        questionTypes,
        new Set(questionTypes.map((type) => type.value)),
    );

    const frequencyLists = await frequencyListResponse.json();
    const lexicons = await lexiconResponse.json();

    for (const input of learningTypeInputs) {
        if (input.value === "word") input.disabled = !supportsWord;
        if (input.value === "symbol") input.disabled = !supportsSymbol;
    }
    if (!supportsWord && supportsSymbol) {
        form.querySelector(".learning-type[value=symbol]").checked = true;
    }
    if (!supportsWord && !supportsSymbol) {
        createStatus.textContent =
            "This language has neither a frequency list nor a known " +
            "alphabet.";
        submitButton.disabled = true;
        return;
    }

    function currentLearningType() {
        return form.querySelector(".learning-type:checked").value;
    }

    function refreshForLearningType() {
        const isWord = currentLearningType() === "word";
        wordFields.hidden = !isWord;
        targets.required = isWord;
        frequencyListSelect.required = isWord;
        if (isWord) {
            fillFrequencyListSelect(
                frequencyListSelect,
                frequencyLists,
                course.language,
            );
            fillLearningLexiconSelect(lexiconSelect, lexicons, course.language);
            fillLearningLexiconSelect(
                askLexiconSelect,
                lexicons,
                course.language,
            );
        }
    }

    for (const input of learningTypeInputs) {
        input.addEventListener("change", refreshForLearningType);
    }
    refreshForLearningType();

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const isWord = currentLearningType() === "word";

        const questionTypesChecked = checkedQuestionTypes(
            questionTypesContainer,
        );
        if (questionTypesChecked.length === 0) {
            createStatus.textContent = "Pick at least one question type.";
            return;
        }

        const body = {
            learning_type: currentLearningType(),
            name: nameInput.value.trim() || null,
            max_for_day: Number(maxForDayInput.value),
            play_audio: playAudioInput.checked,
            question_types: questionTypesChecked,
        };

        if (isWord) {
            const translationLanguages = Array.from(
                targets.selectedOptions,
                (option) => option.value,
            );
            if (translationLanguages.length === 0) {
                createStatus.textContent =
                    "Pick at least one language to translate into.";
                return;
            }
            body.translation_languages = translationLanguages;
            body.frequency_list = decodeFrequencyListValue(
                frequencyListSelect.value,
            );
            body.lexicon_id = lexiconSelect.value || null;
            body.ask_lexicon_id = askLexiconSelect.value || null;
        }

        createStatus.textContent = "Creating…";
        const result = await api(
            `/me/courses/${encodeURIComponent(courseId)}/learnings`,
            { method: "POST", body },
        );
        if (result.ok) {
            const { learning_id } = await result.json();
            location.href = `learn?learning=${encodeURIComponent(
                learning_id,
            )}`;
        } else {
            const { detail } = await result.json().catch(() => ({}));
            createStatus.textContent = detail || "Could not create learning.";
        }
    });
}
