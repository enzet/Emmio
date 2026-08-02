import { createStrataChart, createTrajectoryChart } from "./charts.js";
import { identifierSpan, languageName, loadingDots, relativeTime } from "./format.js";
import { api, requireAuth } from "./api.js";

// Lexicon checking. The client keeps a small queue of upcoming words (each
// with its translation already loading) plus a history stack, so answering
// is instant and any number of answers can be undone. `base` is the
// resource path, e.g. `/me/lexicons/fr`.

const BUFFER_SIZE = 3; // Words kept prefetched ahead of the current one.

async function runSession(base, doneText) {
    const word = document.getElementById("word");
    const status = document.getElementById("status");
    const answers = document.getElementById("answers");
    const notToCheckButton = document.getElementById("not-to-check");
    const notToCheckPanel = document.getElementById(
        "not-to-check-categories",
    );
    const notToCheckBack = document.getElementById("not-to-check-back");
    const translation = document.getElementById("translation");
    const undoBar = document.getElementById("undo-bar");
    const undoWord = document.getElementById("undo-word");
    const question = document.getElementById("question");
    const sentence = document.getElementById("sentence");

    const showButton = document.getElementById("show-translation");
    const showButtonLabel = document.getElementById("show-translation-label");
    const noTranslation = document.getElementById("no-translation");
    const externalLinks = document.getElementById("external-links");
    const googleLink = document.getElementById("google-link");
    const yandexLink = document.getElementById("yandex-link");
    const wiktionaryLink = document.getElementById("wiktionary-link");
    const kaikkiLink = document.getElementById("kaikki-link");

    const queue = []; // Upcoming { word, lastResponse, lastTime, results }.
    const history = []; // Answered { word } (most recent last), for undo.
    let refill = null; // The in-flight refill, so `/next` calls never overlap.
    let current = null; // The item on screen.
    let revealed = false; // Whether the current word's translation is shown.
    let language = null; // ISO code of the session's language (from `/next`).
    let answering = false; // Guards a second click landing before advance().

    // Live "r = 7.23 ± 0.14" estimate, refreshed after every answer.
    // Fire-and-forget: a stale response (superseded by a later request) is
    // dropped.
    const rateEstimate = document.getElementById("rate-estimate");
    let rateRequest = 0;

    // The estimate convergence chart (check page only; the figure is absent
    // elsewhere): seeded with the replayed history, grown per answer.
    const trajectoryFigure = document.getElementById("trajectory");
    const chart = trajectoryFigure
        ? createTrajectoryChart(
              trajectoryFigure,
              document.getElementById("trajectory-svg"),
              document.getElementById("trajectory-tooltip"),
          )
        : null;

    // The stratum wheel, drawn for stratified lexicons only (the trajectory
    // response carries no strata for the other strategies).
    const strataFigure = document.getElementById("strata");
    const strataChart = strataFigure
        ? createStrataChart(
              strataFigure,
              document.getElementById("strata-svg"),
          )
        : null;

    // Seed both charts with the whole history from one response. A lexicon
    // whose strategy has no estimator (or no frequency list) just keeps the
    // charts hidden.
    async function loadTrajectory() {
        if (!chart) return;
        const response = await api(`${base}/rate-trajectory`);
        if (!response.ok) return;
        const data = await response.json();
        chart.setSeed(data, counts.checked);
        if (strataChart && data.strata) {
            strataChart.setSeed(data.strata, data.n_strata, counts.checked);
        }
    }

    // Live session status: answers so far (know/don't know split), plus the
    // current word's frequency rank and (for `stratified`) its stratum.
    const sessionCounts = document.getElementById("session-counts");
    const wordInfo = document.getElementById("word-info");
    const counts = { checked: 0, know: 0, dont: 0 };
    let selection = null; // The lexicon's selection strategy (from `/next`).
    let listSize = null; // Frequency list length (from `/next`).
    let strataCount = null; // Total strata for `stratified` (from `/next`).

    function renderSessionStatus() {
        if (sessionCounts) {
            sessionCounts.textContent =
                `Checked: ${counts.checked} · ` +
                `know: ${counts.know} · don't know: ${counts.dont}`;
            sessionCounts.hidden = false;
        }
        if (!wordInfo) return;
        if (!current || current.rank == null) {
            wordInfo.hidden = true;
            return;
        }
        const parts = [];
        if (selection) parts.push(selection);
        let place = `word #${current.rank.toLocaleString("en-US")}`;
        if (listSize) place += ` of ${listSize.toLocaleString("en-US")}`;
        parts.push(place);
        if (current.stratum != null && strataCount) {
            parts.push(`stratum ${current.stratum + 1}/${strataCount}`);
        }
        wordInfo.textContent = parts.join(" · ");
        wordInfo.hidden = false;
    }

    // Returns whether the trailing-window precision goal is met, so the
    // check loop can stop and hand the session back once it is.
    async function refreshRateEstimate() {
        if (!rateEstimate) return false;
        const token = ++rateRequest;
        // How many session answers this estimate covers, for the chart.
        const checked = counts.checked;
        const response = await api(`${base}/rate-estimate`);
        if (token !== rateRequest || !response.ok) return false;
        const estimate = await response.json();
        if (token !== rateRequest) return false;
        chart?.noteEstimate(checked, estimate.rate, estimate.sd);
        if (estimate.rate === null) {
            rateEstimate.hidden = true;
            return Boolean(estimate.achieved);
        }
        rateEstimate.textContent =
            `r = ${estimate.rate.toFixed(2)} ± ${estimate.sd.toFixed(2)}`;
        rateEstimate.title = `${estimate.method[0].toUpperCase()}${estimate.method.slice(1)} estimate`;
        rateEstimate.hidden = false;
        return Boolean(estimate.achieved);
    }

    // The lexicon/course's dictionaries, loaded once. Each is fetched
    // separately per word so a slow one (e.g. Google Translate over the
    // network) never holds up the fast ones; loaded on demand below.
    let dictionaries = [];

    // Start loading a word's translation now so it's ready when needed. Each
    // dictionary is fetched independently into `item.results` by position
    // (`undefined` until resolved); the reveal button enables as soon as the
    // first one with content arrives.
    function attachTranslation(item) {
        item.results = dictionaries.map(() => undefined);
        dictionaries.forEach(({ index }, slot) => {
            api(
                `${base}/translation?word=${encodeURIComponent(item.word)}` +
                    `&index=${index}`,
            )
                .then((response) => (response.ok ? response.json() : null))
                .then((data) => {
                    item.results[slot] = (data && data.dictionaries) || [];
                    onTranslationProgress(item);
                });
        });
    }

    // React to one of `item`'s dictionaries resolving: enable the reveal
    // button once any has content, or show "No translation found." once all
    // resolved empty. Ignored once the user has moved to another word.
    function onTranslationProgress(item) {
        if (current !== item) return;
        const results = item.results || [];
        const hasContent = results.some((result) => result && result.length);
        const allResolved = results.every((result) => result !== undefined);
        if (hasContent) {
            showButton.disabled = false;
        } else if (allResolved) {
            showButton.hidden = true;
            noTranslation.hidden = false;
        }
        renderTranslation(item);
    }

    // Render one block per dictionary entry into the translation area.
    function appendDictionaries(entries) {
        for (const entry of entries) {
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
            translation.append(block);
        }
    }

    // Likewise the example sentence: a slow Tatoeba lookup, kept off `/next`
    // and prefetched so it appears under the word when ready (HTML or null).
    function attachSentence(item) {
        item.sentence = api(
            `${base}/sentence?word=${encodeURIComponent(item.word)}`,
        )
            .then((response) => (response.ok ? response.json() : null))
            .then((data) => (data ? data.sentence : null));
    }

    // Refill the queue, skipping words already queued. At most one refill
    // runs at a time — server selection can be deterministic, so racing
    // `/next` calls would return the same words and queue duplicates.
    function fill() {
        if (!refill) {
            refill = refillQueue().finally(() => {
                refill = null;
            });
        }
        return refill;
    }

    async function refillQueue() {
        const need = BUFFER_SIZE - queue.length;
        if (need <= 0) return;
        const params = new URLSearchParams({ count: String(need) });
        for (const item of [current, ...queue]) {
            if (item) params.append("exclude", item.word);
        }
        const response = await api(`${base}/next?${params}`);
        if (!response.ok) return;
        const batch = await response.json();
        language = batch.language;
        if (batch.selection) {
            selection = batch.selection;
            listSize = batch.list_size;
            strataCount = batch.strata;
        }
        for (const card of batch.words) {
            // A word already on screen, queued, or answered this session can
            // still come back from a `/next` that raced with an answer being
            // recorded; presenting it again would double-count it.
            if (
                (current && current.word === card.word) ||
                queue.some((item) => item.word === card.word) ||
                history.some((entry) => entry.word === card.word)
            ) {
                continue;
            }
            const item = {
                word: card.word,
                lastResponse: card.last_response,
                lastTime: card.last_time,
                rank: card.rank,
                stratum: card.stratum,
                results: null,
                sentence: null,
            };
            attachTranslation(item);
            attachSentence(item);
            queue.push(item);
        }
    }

    // Show the primary answer buttons (Know/Don't know/…) by default, or the
    // "not to check" subcategory buttons instead once that button is
    // clicked. Never both at once, so a shared shortcut key (e.g. `N` for
    // both "Don't know" and the "Not a word" subcategory) always resolves to
    // whichever one is actually visible.
    function showNotToCheckPanel(show) {
        answers.hidden = show;
        notToCheckPanel.hidden = !show;
    }

    function render() {
        translation.replaceChildren();
        translation.classList.add("blurred");
        revealed = false;
        showButton.hidden = false;
        showButton.disabled = true;
        showButtonLabel.textContent = "Show translation";
        noTranslation.hidden = true;
        undoBar.hidden = history.length === 0;
        if (history.length) {
            undoWord.textContent = history[history.length - 1].word;
        }
        renderLastAnswer();
        renderSentence();
        renderExternalLinks();
        renderSessionStatus();
        word.classList.toggle(
            "top",
            Boolean(current) && current.rank != null && current.rank <= 10000,
        );
        // A fresh word always starts on the primary buttons, even if the
        // previous word was left showing the "not to check" subcategories.
        showNotToCheckPanel(false);
        if (current) {
            word.textContent = current.word;
            status.textContent = "";
            answers.hidden = false;
            // Enable the reveal button now if a dictionary already resolved
            // while this word was queued.
            onTranslationProgress(current);
        } else {
            word.textContent = "";
            answers.hidden = true;
            status.textContent = doneText;
        }
    }

    // Point the external lookup links (Google, Yandex, Wiktionary, Kaikki)
    // at the current word. Hidden when no word is showing.
    function renderExternalLinks() {
        if (!current) {
            externalLinks.hidden = true;
            return;
        }
        const word = encodeURIComponent(current.word);
        const langName = languageName(language);
        const query = `Translate ${langName} word "${current.word}".`;
        googleLink.href =
            `https://www.google.com/search?q=${encodeURIComponent(query)}`;
        yandexLink.href =
            `https://translate.yandex.ru/?source_lang=${encodeURIComponent(language)}` +
            `&target_lang=en&text=${word}`;
        // Wiktionary anchors the per-language section by its English name.
        wiktionaryLink.href =
            `https://en.wiktionary.org/wiki/${word}` +
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

    // Show the current word's example sentence: "Loading…" until its prefetch
    // resolves, then the sentence or "No sentence." Results are ignored if we
    // have since moved to another word.
    function renderSentence() {
        // Keep the sentence box present (fixed height in CSS) so the layout
        // never jumps; fill it with dots, the sentence, or a dash.
        sentence.hidden = false;
        if (!current || !current.sentence) {
            sentence.replaceChildren();
            return;
        }
        sentence.replaceChildren(loadingDots());
        const item = current;
        // The server returns a safe HTML fragment (text escaped, word in <b>).
        item.sentence.then((html) => {
            if (current !== item) return;
            if (html) {
                sentence.innerHTML = html;
            } else {
                sentence.textContent = "—";
            }
        });
    }

    // Show what the user last answered for the current word, and when.
    function renderLastAnswer() {
        if (current && current.lastResponse) {
            const when = current.lastTime
                ? ` (${relativeTime(current.lastTime)})`
                : "";
            question.textContent =
                `Do you know at least one meaning of the word? Last answer was ${current.lastResponse}${when}.`;
        } else {
            question.textContent =
                `Do you know at least one meaning of the word?`;
        }
    }

    // Replace the word/translation/sentence with a loading placeholder, so
    // nothing stale lingers while the next word isn't ready yet (which would
    // read as "did my answer actually not go through?").
    function showLoadingPlaceholder() {
        word.replaceChildren(loadingDots());
        translation.classList.remove("blurred");
        translation.replaceChildren(loadingDots());
        sentence.replaceChildren(loadingDots());
    }

    // Move to the next queued word, topping the queue back up in the
    // background so the wait is hidden behind the user's reading time.
    async function advance() {
        if (queue.length === 0) {
            // No word prefetched yet (first load, or the buffer ran dry):
            // show the placeholder while `/next` is in flight.
            showLoadingPlaceholder();
            status.textContent = "";
            await fill();
            // The awaited refill may have started before the last answer was
            // recorded and had all its words dropped as duplicates; one more
            // round trip reads the settled state.
            if (queue.length === 0) await fill();
        }
        current = queue.shift() || null;
        render();
        void fill();
    }

    async function answer(response, toSkip = false, category = null) {
        if (!current || answering) return;
        answering = true;
        const answered = current.word;
        // Hide already answered word, translation, and sentence.
        showLoadingPlaceholder();
        showNotToCheckPanel(false);
        // Remember the response and strategy context so an undo can both
        // rewind the session counters and re-present the word annotated.
        history.push({
            word: answered,
            response,
            rank: current.rank,
            stratum: current.stratum,
        });
        counts.checked += 1;
        if (response === "know" || response === "know_semantic_class") {
            counts.know += 1;
        } else if (response === "dont") counts.dont += 1;
        if (
            response === "know" ||
            response === "know_semantic_class" ||
            response === "dont"
        ) {
            strataChart?.noteAnswer(
                counts.checked,
                current.stratum,
                response !== "dont",
            );
        }
        try {
            const body = { word: answered, response, to_skip: toSkip };
            if (category) body.category = category;
            await api(`${base}/answer`, { method: "POST", body });
            if (await refreshRateEstimate()) {
                // The trailing-window precision goal is met: the checking
                // process is done, so hand the session back automatically.
                status.textContent = "Goal reached — nice work!";
                location.href = "lexicons";
                return;
            }
            await advance();
        } finally {
            answering = false;
        }
    }

    // Remove the most recent answer and re-present that word to re-answer it.
    // Repeating walks back through the history stack.
    async function undo() {
        if (history.length === 0) return;
        const response = await api(`${base}/undo`, { method: "POST" });
        if (!response.ok) return;
        const { word: undone } = await response.json();
        if (!undone) return;
        const entry = history.pop();
        counts.checked -= 1;
        if (entry.response === "know" || entry.response === "know_semantic_class") {
            counts.know -= 1;
        } else if (entry.response === "dont") counts.dont -= 1;
        chart?.noteUndo(counts.checked);
        if (
            entry.response === "know" ||
            entry.response === "know_semantic_class" ||
            entry.response === "dont"
        ) {
            strataChart?.noteUndo(
                counts.checked,
                entry.stratum,
                entry.response !== "dont",
            );
        }
        if (current) queue.unshift(current);
        current = {
            word: undone,
            rank: entry.rank,
            stratum: entry.stratum,
            results: null,
            sentence: null,
        };
        attachTranslation(current);
        attachSentence(current);
        void refreshRateEstimate();
        render();
    }

    // Toggle the translation between blurred and revealed; the content is
    // already rendered, so this only flips the blur and the button's label.
    function toggleTranslation() {
        if (!current) return;
        revealed = !revealed;
        translation.classList.toggle("blurred", !revealed);
        showButtonLabel.textContent = revealed
            ? "Hide translation"
            : "Show translation";
    }

    // Render every dictionary resolved so far for `item`, in configured
    // order; "Loading…" until the first arrives, "No translation found."
    // once all resolved empty. CSS blur (not this) hides it while unrevealed.
    function renderTranslation(item) {
        if (current !== item) return;
        translation.replaceChildren();
        const results = item.results || [];
        const groups = [];
        for (const result of results) {
            if (result) groups.push(...result);
        }
        if (groups.length) {
            appendDictionaries(groups);
        } else if (results.every((result) => result !== undefined)) {
            translation.textContent = "No translation found.";
        } else {
            translation.replaceChildren(loadingDots());
        }
    }

    // Buttons with `data-response` answer directly (both panels: the
    // primary Know/Don't know buttons and the "not to check" subcategory
    // buttons, which additionally carry `data-category`).
    for (const button of [
        ...answers.querySelectorAll("button[data-response]"),
        ...notToCheckPanel.querySelectorAll("button[data-response]"),
    ]) {
        button.addEventListener("click", () =>
            answer(
                button.dataset.response,
                button.dataset.skip === "true",
                button.dataset.category || null,
            ),
        );
    }
    // "Not to check" and "Back" only toggle which panel is showing — picking
    // a reason is what actually answers (see above).
    notToCheckButton.addEventListener("click", () =>
        showNotToCheckPanel(true),
    );
    notToCheckBack.addEventListener("click", () => showNotToCheckPanel(false));
    document
        .getElementById("show-translation")
        .addEventListener("click", toggleTranslation);
    document.getElementById("undo").addEventListener("click", undo);

    // Keyboard shortcuts: each button's `data-key` triggers a click (matches
    // the CLI), plus space to toggle the translation. The primary and "not
    // to check" panels reuse some keys (e.g. `N` for both "Don't know" and
    // the "Not a word" subcategory) since only one panel is ever visible at
    // once — picking the first non-hidden match resolves that correctly.
    function shortcutButton(event) {
        if (event.ctrlKey || event.metaKey || event.altKey) return null;
        if (event.target.matches("input, textarea, select")) return null;
        const key = event.key === " " ? " " : event.key.toLowerCase();
        for (const button of document.querySelectorAll(
            `button[data-key="${key}"]`,
        )) {
            // `closest("[hidden]")`, not `button.hidden`: a button can be
            // hidden via an ancestor (the whole answers panel, or whichever
            // of the primary/"not to check" panels is not showing) without
            // its own `hidden` property being set.
            if (!button.closest("[hidden]")) return button;
        }
        return null;
    }
    // Act on key *release*, not press: a held key auto-repeats keydown, which
    // would rifle one answer (e.g. "yes") through every buffered word. keydown
    // only suppresses the key's default and arms the key; keyup fires the click
    // once, so each answer needs a deliberate press and release.
    const armedKeys = new Set();
    document.addEventListener("keydown", (event) => {
        if (!shortcutButton(event)) return;
        event.preventDefault();
        armedKeys.add(event.code);
    });
    document.addEventListener("keyup", (event) => {
        if (!armedKeys.delete(event.code)) return;
        const button = shortcutButton(event);
        if (!button) return;
        event.preventDefault();
        // Briefly flash the pressed state so a keyboard shortcut gives the same
        // visual feedback as a mouse click (a programmatic click does not
        // trigger :active).
        button.classList.add("pressed");
        setTimeout(() => button.classList.remove("pressed"), 120);
        button.click();
    });

    word.replaceChildren(loadingDots());
    if (await refreshRateEstimate()) {
        // Reached directly (e.g. a stale link) while the goal is already
        // met: nothing to check, so hand the session back right away.
        status.textContent = "Goal reached — nice work!";
        location.href = "lexicons";
        return;
    }
    void loadTrajectory();
    // Load the dictionary list first so the per-word prefetch knows which
    // dictionaries to request; an empty list just means no translations.
    const dictionariesResponse = await api(`${base}/dictionaries`);
    if (dictionariesResponse.ok) {
        dictionaries = await dictionariesResponse.json();
    }
    await advance();
}

// Lexicon checking page.

export async function initCheck() {
    requireAuth();
    const id = new URLSearchParams(location.search).get("lexicon");
    document.getElementById("lexicon-heading").replaceChildren(
        identifierSpan(id),
    );
    await runSession(
        `/me/lexicons/${encodeURIComponent(id)}`,
        "No more words to check.",
    );
}
