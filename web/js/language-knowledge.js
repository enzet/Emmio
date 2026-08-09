import { api } from "./api.js";

// The value select's synthetic "Other" option: never sent to the API as a
// value itself, just a client-side signal to show the free-text input and
// send *that* as the value instead (see `updateValueField`/submit below).
const OTHER = "__other__";

// Fetch the assessment-kind taxonomy, or `null` if it cannot be loaded.
export async function loadKnowledgeKinds() {
    const response = await api("/language-knowledge-kinds");
    return response.ok ? await response.json() : null;
}

// Wire up the "add an estimate" fields (kind / caption / value / date),
// which together are a small state machine over the kind taxonomy: which
// fields exist at all, and what shape the value field takes, depend entirely
// on the chosen kind.
//
// Shared by the two places an estimate is entered — a language's own page
// (`initLanguageEstimates`) and the add-a-language form, where the first
// estimate is mandatory — so both pages use the same element ids and get the
// same behavior. Returns `setLanguage`, since the offerable kinds depend on
// the language (HSK never shows up for French), and `collect`, which reads
// the fields back the way the API expects them.
export function setupEstimateFields(kinds, language) {
    const kindSelect = document.getElementById("add-knowledge-kind");
    const captionField = document.getElementById(
        "add-knowledge-caption-field",
    );
    const captionInput = document.getElementById("add-knowledge-caption");
    const valueField = document.getElementById("add-knowledge-value-field");
    const valueSelect = document.getElementById("add-knowledge-value-select");
    const valueNumber = document.getElementById(
        "add-knowledge-value-number",
    );
    const valueOther = document.getElementById("add-knowledge-value-other");
    const valueFieldLabel = document.querySelector(
        'label[for="add-knowledge-value-select"]',
    );
    const dateField = document.getElementById("add-knowledge-date-field");
    const dateInput = document.getElementById("add-knowledge-date");

    let currentLanguage = language;

    function currentKind() {
        return kinds.find((kind) => kind.code === kindSelect.value);
    }

    // Only a kind that applies to any language, or names this one, may be
    // picked — e.g. HSK never shows up for French.
    function fillKindSelect() {
        kindSelect.innerHTML = "";
        for (const kind of kinds) {
            if (
                kind.languages !== null &&
                !kind.languages.includes(currentLanguage)
            ) {
                continue;
            }
            const option = document.createElement("option");
            option.value = kind.code;
            option.textContent = kind.label;
            kindSelect.appendChild(option);
        }
    }

    // "Standardized test" names itself via free text instead of a fixed
    // label; every other kind leaves this row hidden.
    function updateCaptionField() {
        const kind = currentKind();
        captionField.hidden = !kind?.has_caption;
        captionInput.required = !!kind?.has_caption;
        if (!kind?.has_caption) captionInput.value = "";
    }

    // Two reasons the date row can be hidden, and they mean different
    // things: `native` is undated outright (a learner is not native "as of"
    // some date), while a self-assessment *is* dated but always as of today,
    // so asking is pure friction — the server stamps it (`implicit_date`,
    // see `resolve_knowledge_date`). Either way nothing is sent.
    function updateDateField() {
        const kind = currentKind();
        const asksForDate = kind
            ? kind.requires_date && !kind.implicit_date
            : true;
        dateField.hidden = !asksForDate;
        dateInput.required = asksForDate;
        if (!asksForDate) dateInput.value = "";
        else if (!dateInput.value) {
            dateInput.value = new Date().toISOString().slice(0, 10);
        }
    }

    // The value field's shape depends entirely on the chosen kind: a
    // dropdown for a discrete scale (CEFR, HSK, ...), plus an "Other" entry
    // when the kind allows one; a number input for a continuous scale
    // (IELTS, TOEFL); free text alone when there is no curated scale at all
    // but "Other" is still allowed (Standardized test); or nothing (native
    // speaker).
    function updateValueField() {
        const kind = currentKind();
        valueSelect.hidden = true;
        valueSelect.required = false;
        valueSelect.innerHTML = "";
        valueNumber.hidden = true;
        valueNumber.required = false;
        valueOther.hidden = true;
        valueOther.required = false;
        valueOther.value = "";
        // A kind with no value scale at all (native speaker) hides the
        // whole row — see the `.add-form .field[hidden]` CSS rule.
        valueField.hidden =
            !kind ||
            (!kind.numeric_range &&
                kind.values.length === 0 &&
                !kind.allows_other);
        if (!kind) return;
        if (kind.numeric_range) {
            valueNumber.hidden = false;
            valueNumber.required = true;
            valueNumber.min = kind.numeric_range.minimum;
            valueNumber.max = kind.numeric_range.maximum;
            valueNumber.step = kind.numeric_range.step;
            valueNumber.value = "";
            valueFieldLabel.htmlFor = "add-knowledge-value-number";
        } else if (kind.values.length > 0) {
            valueSelect.hidden = false;
            valueSelect.required = true;
            for (const value of kind.values) {
                const option = document.createElement("option");
                option.value = value.code;
                option.textContent = value.label;
                valueSelect.appendChild(option);
            }
            if (kind.allows_other) {
                const option = document.createElement("option");
                option.value = OTHER;
                option.textContent = "Other";
                valueSelect.appendChild(option);
            }
            updateOtherVisibility();
            valueFieldLabel.htmlFor = "add-knowledge-value-select";
        } else if (kind.allows_other) {
            // No curated scale at all (Standardized test): skip the
            // dropdown, the value is free text directly.
            valueOther.hidden = false;
            valueOther.required = true;
            valueFieldLabel.htmlFor = "add-knowledge-value-other";
        }
    }

    // Show the free-text input only while the dropdown's "Other" entry is
    // selected; called on every value-select change, not just kind change.
    function updateOtherVisibility() {
        const isOther = valueSelect.value === OTHER;
        valueOther.hidden = !isOther;
        valueOther.required = isOther;
        if (!isOther) valueOther.value = "";
    }

    function refresh() {
        fillKindSelect();
        updateCaptionField();
        updateValueField();
        updateDateField();
    }

    kindSelect.addEventListener("change", () => {
        updateCaptionField();
        updateValueField();
        updateDateField();
    });
    valueSelect.addEventListener("change", updateOtherVisibility);
    refresh();

    return {
        // Re-offer the kinds that apply to a newly chosen language, and
        // reset the dependent fields to match.
        setLanguage(next) {
            currentLanguage = next;
            refresh();
        },
        // Read the fields back in the shape the API takes. Which control
        // holds the value depends on the kind, so this mirrors
        // `updateValueField`'s branches.
        collect() {
            const kind = currentKind();
            let value = null;
            if (kind?.numeric_range) {
                value = valueNumber.value;
            } else if (kind?.values.length > 0) {
                value =
                    valueSelect.value === OTHER
                        ? valueOther.value
                        : valueSelect.value;
            } else if (kind?.allows_other) {
                value = valueOther.value;
            }
            return {
                kind: kindSelect.value,
                value: value || null,
                caption: kind?.has_caption ? captionInput.value || null : null,
                // Left null for an `implicit_date` kind too, which is what
                // tells the server to stamp today.
                date:
                    kind?.requires_date && !kind.implicit_date
                        ? dateInput.value
                        : null,
            };
        },
    };
}

function kindLabel(kinds, record) {
    const label = kinds.find((kind) => kind.code === record.kind)?.label;
    if (!label) return record.kind;
    return record.caption ? `${label}: ${record.caption}` : label;
}

function valueLabel(kinds, kindCode, value) {
    if (value === null || value === undefined) return "—";
    const values = kinds.find((kind) => kind.code === kindCode)?.values;
    return values?.find((entry) => entry.code === value)?.label ?? value;
}

// Self-reported proficiency estimates for one language: native speaker /
// self-assessed / teacher-assessed / a certifying organization, each
// carrying its own value scale (see `emmio.language_knowledge`). Distinct
// from a lexicon's computed rate; every estimate added is kept, never
// overwritten.
//
// Scoped to a single language because this lives on that language's own page
// (see `initLanguage`): the language is fixed by the URL rather than picked
// in the form, and the list shows only this language's estimates.
export async function initLanguageEstimates(language) {
    const table = document.getElementById("knowledge-table");
    const rows = document.getElementById("knowledge-rows");
    const knowledgeStatus = document.getElementById("knowledge-status");
    const form = document.getElementById("add-knowledge-form");
    const addStatus = document.getElementById("add-knowledge-status");

    const kinds = await loadKnowledgeKinds();
    if (kinds === null) {
        knowledgeStatus.textContent = "Could not load assessment kinds.";
        return;
    }
    const fields = setupEstimateFields(kinds, language);

    async function loadRecords() {
        const response = await api("/me/language-knowledge");
        if (!response.ok) {
            knowledgeStatus.textContent = "Could not load your estimates.";
            return;
        }
        const records = (await response.json()).filter(
            (record) => record.language === language,
        );
        rows.innerHTML = "";
        table.hidden = records.length === 0;
        knowledgeStatus.textContent =
            records.length === 0 ? "No estimates for this language yet." : "";
        for (const record of records) {
            const row = document.createElement("tr");

            const kindCell = document.createElement("td");
            kindCell.textContent = kindLabel(kinds, record);
            row.appendChild(kindCell);

            const valueCell = document.createElement("td");
            valueCell.textContent = valueLabel(kinds, record.kind, record.value);
            row.appendChild(valueCell);

            const dateCell = document.createElement("td");
            dateCell.textContent = record.date ?? "—";
            row.appendChild(dateCell);

            const actionCell = document.createElement("td");
            const deleteButton = document.createElement("button");
            deleteButton.type = "button";
            deleteButton.className = "danger";
            deleteButton.textContent = "\uE005 Delete";
            deleteButton.addEventListener("click", async () => {
                const result = await api(
                    `/me/language-knowledge/${record.id}`,
                    { method: "DELETE" },
                );
                if (result.ok) loadRecords();
            });
            actionCell.appendChild(deleteButton);
            row.appendChild(actionCell);

            rows.appendChild(row);
        }
    }

    await loadRecords();

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        addStatus.textContent = "Adding…";
        const result = await api("/me/language-knowledge", {
            method: "POST",
            body: { language, ...fields.collect() },
        });
        if (result.ok) {
            addStatus.textContent = "";
            await loadRecords();
        } else {
            const { detail } = await result.json().catch(() => ({}));
            addStatus.textContent = detail || "Could not add estimate.";
        }
    });
}
