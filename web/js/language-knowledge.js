import { fillLanguageSelect, languageName } from "./format.js";
import { api, requireAuth } from "./api.js";

// The value select's synthetic "Other" option: never sent to the API as a
// value itself, just a client-side signal to show the free-text input and
// send *that* as the value instead (see `updateValueField`/submit below).
const OTHER = "__other__";

// Self-reported language knowledge: native speaker / self-assessed /
// teacher-assessed / a certifying organization, each carrying its own value
// scale (see `emmio.language_knowledge`). Distinct from a lexicon's
// computed rate; every estimate added is kept, never overwritten.
export async function initLanguages() {
    requireAuth();

    const status = document.getElementById("status");
    const table = document.getElementById("knowledge-table");
    const rows = document.getElementById("knowledge-rows");
    const knowledgeStatus = document.getElementById("knowledge-status");

    const form = document.getElementById("add-knowledge-form");
    const languageSelect = document.getElementById("add-knowledge-language");
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
    const addStatus = document.getElementById("add-knowledge-status");

    const [languagesResponse, kindsResponse] = await Promise.all([
        api("/translation-languages"),
        api("/language-knowledge-kinds"),
    ]);
    if (!languagesResponse.ok || !kindsResponse.ok) {
        status.textContent = "Could not load languages or assessment kinds.";
        return;
    }
    const languages = await languagesResponse.json();
    const kinds = await kindsResponse.json();

    fillLanguageSelect(languageSelect, languages);

    function currentKind() {
        return kinds.find((kind) => kind.code === kindSelect.value);
    }

    // Only a kind that applies to any language, or names the chosen one,
    // may be picked — e.g. HSK never shows up for French.
    function fillKindSelect() {
        kindSelect.innerHTML = "";
        for (const kind of kinds) {
            if (
                kind.languages !== null &&
                !kind.languages.includes(languageSelect.value)
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

    // `native` needs no date — a learner is not native "as of" some date —
    // so its row is hidden and nothing is sent, mirroring the caption field.
    function updateDateField() {
        const kind = currentKind();
        const requiresDate = kind ? kind.requires_date : true;
        dateField.hidden = !requiresDate;
        dateInput.required = requiresDate;
        if (!requiresDate) dateInput.value = "";
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

    languageSelect.addEventListener("change", () => {
        fillKindSelect();
        updateCaptionField();
        updateValueField();
        updateDateField();
    });
    kindSelect.addEventListener("change", () => {
        updateCaptionField();
        updateValueField();
        updateDateField();
    });
    valueSelect.addEventListener("change", updateOtherVisibility);
    fillKindSelect();
    updateCaptionField();
    updateValueField();
    updateDateField();

    function kindLabel(record) {
        const label = kinds.find((kind) => kind.code === record.kind)?.label;
        if (!label) return record.kind;
        return record.caption ? `${label}: ${record.caption}` : label;
    }

    function valueLabel(kindCode, value) {
        if (value === null || value === undefined) return "—";
        const values = kinds.find((kind) => kind.code === kindCode)?.values;
        return values?.find((entry) => entry.code === value)?.label ?? value;
    }

    async function loadRecords() {
        const response = await api("/me/language-knowledge");
        if (!response.ok) {
            knowledgeStatus.textContent = "Could not load your estimates.";
            return;
        }
        const records = await response.json();
        rows.innerHTML = "";
        table.hidden = records.length === 0;
        knowledgeStatus.textContent =
            records.length === 0 ? "No estimates yet." : "";
        for (const record of records) {
            const row = document.createElement("tr");

            const languageCell = document.createElement("td");
            languageCell.textContent = languageName(record.language);
            row.appendChild(languageCell);

            const kindCell = document.createElement("td");
            kindCell.textContent = kindLabel(record);
            row.appendChild(kindCell);

            const valueCell = document.createElement("td");
            valueCell.textContent = valueLabel(record.kind, record.value);
            row.appendChild(valueCell);

            const dateCell = document.createElement("td");
            dateCell.textContent = record.date ?? "—";
            row.appendChild(dateCell);

            const actionCell = document.createElement("td");
            const deleteButton = document.createElement("button");
            deleteButton.type = "button";
            deleteButton.textContent = "Delete";
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

    status.textContent = "";
    await loadRecords();

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
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

        addStatus.textContent = "Adding…";
        const result = await api("/me/language-knowledge", {
            method: "POST",
            body: {
                language: languageSelect.value,
                kind: kindSelect.value,
                value: value || null,
                caption: kind?.has_caption ? captionInput.value || null : null,
                date: kind?.requires_date ? dateInput.value : null,
            },
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
