import { checkedQuestionTypes, fillLearningLexiconSelect, renderQuestionTypeCheckboxes, setupCreateCourse, setupCreateLearning } from "./forms.js";
import { fillLanguageSelect, languageName, renderDefinitionList } from "./format.js";
import { api, requireAuth } from "./api.js";

// Add-a-course / add-a-learning pages.
//
// Each lives on its own page (`new-course.html` / `new-learning.html`) with
// the form markup written directly in the HTML; these just wire it up.
export async function initNewCourse() {
    requireAuth();
    await setupCreateCourse(
        "add-course-form",
        "add-course-language",
        "add-course-status",
    );
}

export async function initNewLearning() {
    requireAuth();
    const courseId = new URLSearchParams(location.search).get("course");
    document.getElementById("back-to-course").href =
        `course?course=${encodeURIComponent(courseId)}`;
    await setupCreateLearning(
        courseId,
        "add-learning-form",
        "add-learning-status",
    );
}

// Courses list page.

export async function initCourses() {
    requireAuth();

    document
        .getElementById("add-course-button")
        .addEventListener("click", () => {
            location.href = "new-course";
        });

    const status = document.getElementById("status");
    const table = document.getElementById("course-table");
    const rows = document.getElementById("course-rows");
    const response = await api("/me/courses");
    const courses = await response.json();

    if (courses.length === 0) {
        status.textContent = "No courses yet.";
    } else {
        status.textContent = "";
        table.hidden = false;
    }
    for (const course of courses) {
        const row = document.createElement("tr");

        const idCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = `course?course=${encodeURIComponent(
            course.course_id,
        )}`;
        link.textContent = course.name;
        idCell.appendChild(link);
        row.appendChild(idCell);

        for (const value of [
            languageName(course.language),
            course.learning_count,
        ]) {
            const cell = document.createElement("td");
            cell.textContent = value;
            row.appendChild(cell);
        }

        rows.appendChild(row);
    }
}

// Course detail page.

export async function initCourse() {
    requireAuth();

    const courseId = new URLSearchParams(location.search).get("course");
    const status = document.getElementById("status");
    const table = document.getElementById("learning-table");
    const rows = document.getElementById("learning-rows");
    const response = await api(
        `/me/courses/${encodeURIComponent(courseId)}`,
    );
    if (!response.ok) {
        status.textContent = "Could not load course.";
        return;
    }
    const course = await response.json();
    status.textContent = "";

    document.getElementById("course-heading").textContent =
        `Course: ${course.name}`;
    document.getElementById("add-learning-link").href =
        `new-learning?course=${encodeURIComponent(courseId)}`;

    // Settings: currently just the course's name (its language is fixed).
    const settingsSection = document.getElementById("settings-section");
    const settingsForm = document.getElementById("settings-form");
    const nameInput = document.getElementById("setting-name");
    const settingsStatus = document.getElementById("settings-status");
    nameInput.value = course.name;
    settingsSection.hidden = false;
    settingsForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        settingsStatus.textContent = "Saving…";
        const result = await api(
            `/me/courses/${encodeURIComponent(courseId)}`,
            { method: "PATCH", body: { name: nameInput.value.trim() } },
        );
        if (result.ok) {
            const updated = await result.json();
            document.getElementById("course-heading").textContent =
                `Course: ${updated.name}`;
            settingsStatus.textContent = "Saved.";
        } else {
            const { detail } = await result.json().catch(() => ({}));
            settingsStatus.textContent = detail || "Could not save settings.";
        }
    });

    if (course.learnings.length > 0) table.hidden = false;
    for (const learning of course.learnings) {
        const row = document.createElement("tr");

        const idCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = `learning?learning=${encodeURIComponent(
            learning.learning_id,
        )}&course=${encodeURIComponent(courseId)}`;
        link.textContent = learning.name;
        idCell.appendChild(link);
        row.appendChild(idCell);

        for (const value of [
            learning.learning_type === "symbol" ? "Alphabet" : "Vocabulary",
            learning.words,
            learning.answers,
        ]) {
            const cell = document.createElement("td");
            cell.textContent = value;
            row.appendChild(cell);
        }

        rows.appendChild(row);
    }

    // Delete: only allowed while the course has no learnings left.
    const danger = document.getElementById("danger");
    const deleteStatus = document.getElementById("delete-status");
    danger.hidden = false;
    document
        .getElementById("delete-course")
        .addEventListener("click", async () => {
            if (
                !confirm(`Delete course "${course.name}"? This cannot be undone.`)
            ) {
                return;
            }
            deleteStatus.textContent = "Deleting…";
            const result = await api(
                `/me/courses/${encodeURIComponent(courseId)}`,
                { method: "DELETE" },
            );
            if (result.ok) {
                location.href = "courses";
            } else {
                const { detail } = await result.json().catch(() => ({}));
                deleteStatus.textContent =
                    detail || "Could not delete course.";
            }
        });
}

// Learning detail page (settings, statistics, delete).

export async function initLearning() {
    requireAuth();

    const params = new URLSearchParams(location.search);
    const learningId = params.get("learning");
    const courseId = params.get("course");
    if (courseId) {
        document.getElementById("back-to-course").href =
            `course?course=${encodeURIComponent(courseId)}`;
    }
    document.getElementById("learning-heading").textContent =
        `Learning: ${learningId}`;
    document.getElementById("learn-link").href =
        `learn?learning=${encodeURIComponent(learningId)}`;

    const status = document.getElementById("status");
    const stats = document.getElementById("stats");
    const response = await api(
        `/me/learnings/${encodeURIComponent(learningId)}/stats`,
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
    renderDefinitionList(stats, rows);

    await setupLearningSettings(learningId);

    // Delete: removes the learning and all its history, then returns to the
    // parent course (or the courses list, if it isn't known).
    const danger = document.getElementById("danger");
    const deleteStatus = document.getElementById("delete-status");
    danger.hidden = false;
    document
        .getElementById("delete-learning")
        .addEventListener("click", async () => {
            if (
                !confirm(
                    `Delete learning "${learningId}" and all its history? ` +
                        "This cannot be undone.",
                )
            ) {
                return;
            }
            deleteStatus.textContent = "Deleting…";
            const result = await api(
                `/me/learnings/${encodeURIComponent(learningId)}`,
                { method: "DELETE" },
            );
            if (result.ok) {
                location.href = courseId
                    ? `course?course=${encodeURIComponent(courseId)}`
                    : "courses";
            } else {
                deleteStatus.textContent = "Could not delete learning.";
            }
        });
}

// Fill and wire the learning settings form: name, translation targets
// (regenerate dictionaries/sentences/audio on save), the daily new-word
// limit, allowed question types, and the two optional lexicon references
// (skip known words / ask about unseen ones first).
async function setupLearningSettings(learningId) {
    const base = `/me/learnings/${encodeURIComponent(learningId)}`;
    const section = document.getElementById("settings-section");
    const learningTypeLabel = document.getElementById(
        "setting-learning-type",
    );
    const form = document.getElementById("settings-form");
    const wordFields = form.querySelector(".learning-word-fields");
    const nameInput = document.getElementById("setting-name");
    const targets = document.getElementById("setting-targets");
    const maxInput = document.getElementById("setting-max");
    const playAudioInput = document.getElementById("setting-play-audio");
    const questionTypesContainer = document.getElementById(
        "setting-question-types",
    );
    const lexiconSelect = document.getElementById("setting-lexicon");
    const askLexiconSelect = document.getElementById("setting-ask-lexicon");
    const settingsStatus = document.getElementById("settings-status");

    const [
        settingsResponse,
        targetResponse,
        questionTypeResponse,
        lexiconResponse,
    ] = await Promise.all([
        api(`${base}/settings`),
        api("/translation-languages"),
        api("/question-types"),
        api("/me/lexicons"),
    ]);
    if (!settingsResponse.ok) return;
    const settings = await settingsResponse.json();
    const isWord = settings.learning_type === "word";

    learningTypeLabel.textContent = isWord ? "vocabulary" : "alphabet";
    wordFields.hidden = !isWord;
    targets.required = isWord;

    nameInput.value = settings.name;
    maxInput.value = settings.max_for_day;
    playAudioInput.checked = settings.play_audio;
    fillLanguageSelect(
        targets,
        await targetResponse.json(),
        new Set(settings.translation_languages),
    );

    const questionTypes = await questionTypeResponse.json();
    renderQuestionTypeCheckboxes(
        questionTypesContainer,
        "setting-question-type",
        questionTypes,
        new Set(settings.question_types),
    );

    const lexicons = await lexiconResponse.json();
    fillLearningLexiconSelect(
        lexiconSelect,
        lexicons,
        settings.learning_language,
        settings.lexicon_id,
    );
    fillLearningLexiconSelect(
        askLexiconSelect,
        lexicons,
        settings.learning_language,
        settings.ask_lexicon_id,
    );

    section.hidden = false;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const questionTypesChecked = checkedQuestionTypes(
            questionTypesContainer,
        );
        if (questionTypesChecked.length === 0) {
            settingsStatus.textContent = "Pick at least one question type.";
            return;
        }
        const body = {
            name: nameInput.value.trim(),
            max_for_day: Number(maxInput.value),
            play_audio: playAudioInput.checked,
            // Every type checked means "no restriction"; send an empty list
            // so the server clears any previously narrowed set.
            question_types:
                questionTypesChecked.length === questionTypes.length
                    ? []
                    : questionTypesChecked,
        };
        if (isWord) {
            const translationLanguages = Array.from(
                targets.selectedOptions,
                (option) => option.value,
            );
            if (translationLanguages.length === 0) {
                settingsStatus.textContent =
                    "Pick at least one language to translate into.";
                return;
            }
            body.translation_languages = translationLanguages;
            body.lexicon_id = lexiconSelect.value;
            body.ask_lexicon_id = askLexiconSelect.value;
        }
        settingsStatus.textContent = "Saving…";
        const result = await api(`${base}/settings`, {
            method: "PATCH",
            body,
        });
        if (result.ok) {
            settingsStatus.textContent = "Saved.";
        } else {
            const { detail } = await result.json().catch(() => ({}));
            settingsStatus.textContent = detail || "Could not save settings.";
        }
    });
}
