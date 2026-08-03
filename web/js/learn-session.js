import { identifierSpan, languageName, loadingDots, relativeTime } from "./format.js";
import { api, requireAuth } from "./api.js";

// Learning session (production recall): the word is blanked and the user types
// it, auto-accepted the instant the entry matches the card's `accepted` forms.
// Due repetitions come first (`/next`); then new words (`/new`), which may first
// run a know/don't-know lexicon check (`check_lexicon`) before being taught.

async function runLearnSession(base) {
    const status = document.getElementById("status");
    const undoBar = document.getElementById("undo-bar");
    const undoWord = document.getElementById("undo-word");

    // Type-the-word box.
    const teachBox = document.getElementById("teach-box");
    const wordEl = document.getElementById("word");
    const input = document.getElementById("answer-input");
    const symbolButtons = document.getElementById("symbol-buttons");
    const answers = document.getElementById("answers");
    const question = document.getElementById("question");
    const translation = document.getElementById("translation");
    const sentence = document.getElementById("sentence");
    const sentenceTranslation = document.getElementById("sentence-translation");
    const externalLinks = document.getElementById("external-links");
    const googleLink = document.getElementById("google-ai-link");
    const yandexLink = document.getElementById("yandex-link");
    const wiktionaryLink = document.getElementById("wiktionary-link");
    const kaikkiLink = document.getElementById("kaikki-link");
    const continueBar = document.getElementById("continue-bar");
    const continueButton = document.getElementById("continue");
    const cardStatus = document.getElementById("card-status");

    // Know box.
    const knowBox = document.getElementById("know-box");
    const knowHeading = document.getElementById("know-heading");
    const knowWord = document.getElementById("know-word");
    const knowShowBar = document.getElementById("know-show-bar");
    const knowShow = document.getElementById("know-show");
    const knowShowLabel = document.getElementById("know-show-label");
    const knowAnswers = document.getElementById("know-answers");
    const knowMeaning = document.getElementById("know-meaning");
    const knowContinueBar = document.getElementById("know-continue-bar");
    const knowContinue = document.getElementById("know-continue");

    // Choice box.
    const choiceBox = document.getElementById("choice-box");
    const choiceWord = document.getElementById("choice-word");
    const choiceOptions = document.getElementById("choice-options");
    const choiceContinueBar = document.getElementById("choice-continue-bar");
    const choiceContinue = document.getElementById("choice-continue");

    // Connect box.
    const connectBox = document.getElementById("connect-box");
    const connectWords = document.getElementById("connect-words");
    const connectTranslations = document.getElementById("connect-translations");
    const connectContinueBar = document.getElementById("connect-continue-bar");
    const connectContinue = document.getElementById("connect-continue");

    // Ask box (new-word lexicon check).
    const askBox = document.getElementById("ask-box");
    const askWord = document.getElementById("ask-word");

    const history = []; // Answered words (most recent last), for undo.
    const handledNew = new Set(); // New words decided this session.
    let current = null; // The current question/item (carries a `type`).
    let answeredWrong = false; // type_word: word revealed after "I don't know".
    let presentedAt = 0; // When the current card was shown (for `request_time`).
    let language = null;
    let dictionaries = [];
    let newExhausted = false; // `/new` has nothing more to offer.
    let playAudio = true; // Learning setting: play pronunciation audio.

    // Show exactly one question box and hide the rest.
    function showBox(name) {
        teachBox.hidden = name !== "type";
        knowBox.hidden = name !== "know";
        choiceBox.hidden = name !== "choice";
        connectBox.hidden = name !== "connect";
        askBox.hidden = name !== "ask";
    }

    // Render dictionary entries (safe HTML fragments) into a container.
    function appendDictionaries(container, entries) {
        for (const entry of entries) {
            const block = document.createElement("div");
            block.className = "dictionary";
            const name = document.createElement("div");
            name.className = "dictionary-name";
            name.textContent = entry.dictionary;
            const body = document.createElement("div");
            body.className = "dictionary-body";
            body.innerHTML = entry.html; // Safe HTML fragment from the server.
            block.append(name, body);
            container.append(block);
        }
    }

    // Prefetch a word's meaning (word blanked by the server) for type_word;
    // each dictionary resolves independently so a slow one never blocks.
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
                    if (current === item) renderMeaning(item);
                });
        });
    }
    function renderMeaning(item) {
        if (current !== item) return;
        translation.replaceChildren();
        const results = item.results || [];
        const groups = [];
        for (const result of results) if (result) groups.push(...result);
        if (groups.length) {
            appendDictionaries(translation, groups);
        } else if (results.every((result) => result !== undefined)) {
            translation.textContent = "No translation found.";
        } else {
            translation.textContent = "Loading…";
        }
    }
    // The course `/sentence` blanks the target word and pairs the example with
    // one of its translations, both shown as the recall prompt. The example's
    // id is remembered so it can be recorded as provenance with the answer.
    function attachSentence(item) {
        item.sentenceId = null;
        item.sentence = api(
            `${base}/sentence?word=${encodeURIComponent(item.word)}`,
        )
            .then((response) => (response.ok ? response.json() : null))
            .then((data) => {
                if (data && data.sentence) {
                    item.sentenceId = data.sentence_id ?? null;
                    return { html: data.sentence, translation: data.translation };
                }
                return null;
            });
    }
    // Play a word's pronunciation. Fetched as a blob through `api` (an
    // <audio src> can't send the bearer token) and played from an object
    // URL; best-effort, missing audio or an autoplay refusal is ignored.
    let audioUrl = null;
    async function playWordAudio(word) {
        if (!playAudio) return;
        const response = await api(
            `${base}/audio?word=${encodeURIComponent(word)}`,
        );
        if (!response.ok) return;
        const blob = await response.blob();
        if (audioUrl) URL.revokeObjectURL(audioUrl);
        audioUrl = URL.createObjectURL(blob);
        new Audio(audioUrl).play().catch(() => {});
    }

    // Build a type_word item (the typed-recall card), kicking off its meaning
    // and example prefetch.
    function makeItem(card) {
        const item = {
            type: "type_word",
            word: card.word,
            accepted: card.accepted || [card.word],
            source: card.source || "review",
            checkLexicon: card.checkLexicon || null,
            results: null,
            sentence: null,
        };
        attachTranslation(item);
        attachSentence(item);
        return item;
    }

    // Get the next due review question from the server, which chooses its type
    // (type_word / know / choice / connect). `null` when nothing is due.
    async function fetchQuestion() {
        const response = await api(`${base}/question`);
        if (!response.ok) return null;
        const data = await response.json();
        if (data.language) language = data.language;
        return data.type ? data : null;
    }

    // Get one new word to add from `/new` (or null when none remains), skipping
    // words already decided this session.
    async function fetchNew() {
        if (newExhausted) return null;
        const params = new URLSearchParams();
        for (const word of handledNew) params.append("exclude", word);
        const response = await api(`${base}/new?${params}`);
        if (!response.ok) return null;
        const data = await response.json();
        if (!data.word) {
            newExhausted = true;
            return null;
        }
        // A never-seen word can't be typed from its meaning, so first
        // exposure is a `know` card unless an `ask_lexicon` check already
        // asked know/don't-know — then typing follows instead.
        if (!data.check_lexicon && data.question_type === "know") {
            return { type: "know", word: data.word, source: "new" };
        }
        return makeItem({
            word: data.word,
            accepted: data.accepted,
            source: "new",
            checkLexicon: data.check_lexicon,
        });
    }

    // Show the current word's streak and when it was last answered. Empty
    // for connect cards (several words at once) and for new words.
    function renderCardStatus(q) {
        if (!q || q.streak == null) {
            cardStatus.textContent = "";
            return;
        }
        const when = q.last_answer_time
            ? ` · last answered ${relativeTime(q.last_answer_time)}`
            : "";
        cardStatus.textContent = `Streak: ${q.streak}${when}`;
    }

    // Present a server-chosen review question by its type.
    function presentReview(q) {
        renderCardStatus(q);
        if (q.type === "type_word") {
            current = makeItem({ word: q.words[0], accepted: q.accepted });
            renderTeach();
        } else if (q.type === "know") {
            current = { type: "know", word: q.words[0] };
            renderKnow();
        } else if (q.type === "choice") {
            current = {
                type: "choice",
                word: q.words[0],
                options: q.options,
                answer: q.answer,
            };
            renderChoice();
        } else if (q.type === "connect") {
            current = { type: "connect", pairs: q.pairs };
            renderConnect();
        }
    }

    // Pick the next thing to present: a due review question first, then a
    // new word (see `fetchNew`).
    async function advance() {
        answeredWrong = false;
        status.textContent = "Loading…";
        const q = await fetchQuestion();
        status.textContent = "";
        if (q) {
            presentReview(q);
            return;
        }
        const item = await fetchNew();
        if (item) {
            // A new word has no streak or last answer to show.
            cardStatus.textContent = "New word — never answered yet.";
            current = item;
            if (item.checkLexicon) renderAsk();
            else if (item.type === "know") renderKnow();
            else renderTeach();
            return;
        }
        current = null;
        renderCardStatus(null);
        renderDone();
    }

    // Teaching: show the meaning (word blanked) and a translated example as the
    // prompt, blank the word's answer slot, and await typing.
    function renderTeach() {
        showBox("type");
        answeredWrong = false;
        continueBar.hidden = true;
        answers.hidden = false;
        input.hidden = false;
        input.value = "";
        input.disabled = false;
        undoBar.hidden = history.length === 0;
        if (history.length) {
            undoWord.textContent = history[history.length - 1].word;
        }
        wordEl.textContent = "_".repeat([...current.word].length);
        question.textContent =
            current.source === "new" ? "New word — type it." : "Type the word.";
        status.textContent = "";
        presentedAt = Date.now();
        renderMeaning(current);
        renderSentence();
        renderExternalLinks();
        input.focus();
    }

    // New-word check: ask whether the user already knows it (recorded in the
    // course's `ask_lexicon`).
    function renderAsk() {
        showBox("ask");
        askWord.textContent = current.word;
        status.textContent = "";
        undoBar.hidden = history.length === 0;
    }

    function renderDone() {
        showBox("type");
        input.hidden = true;
        answers.hidden = true;
        continueBar.hidden = true;
        wordEl.textContent = "";
        sentence.hidden = true;
        sentenceTranslation.hidden = true;
        question.textContent = "";
        externalLinks.hidden = true;
        translation.replaceChildren();
        status.textContent = "Nothing to learn right now.";
        undoBar.hidden = history.length === 0;
    }

    // Know: see the word, self-assess Know/Don't-know; either way the full
    // meaning is shown throughout, blurred until "Show translation" is
    // pressed or the word is self-assessed.
    function renderKnow() {
        showBox("know");
        status.textContent = "";
        undoBar.hidden = history.length === 0;
        if (history.length) {
            undoWord.textContent = history[history.length - 1].word;
        }
        knowHeading.textContent =
            current.source === "new"
                ? "New word — do you know it?"
                : "Do you know this word?";
        knowWord.textContent = current.word;
        knowShowBar.hidden = false;
        knowShowLabel.textContent = "Show translation";
        knowAnswers.hidden = false;
        knowMeaning.hidden = false;
        knowMeaning.classList.add("blurred");
        knowMeaning.replaceChildren(loadingDots());
        knowContinueBar.hidden = true;
        current.pendingResponse = null;
        presentedAt = Date.now();
        void loadKnowMeaning(current);
    }
    // Fetch the card's full meaning (word shown) into the (blurred) meaning
    // area, so it is ready the instant it needs to be legible.
    async function loadKnowMeaning(item) {
        const groups = [];
        await Promise.all(
            dictionaries.map(async ({ index }) => {
                const response = await api(
                    `${base}/translation?word=${encodeURIComponent(item.word)}` +
                        `&index=${index}&hide_word=false`,
                );
                if (response.ok) {
                    const data = await response.json();
                    if (data.dictionaries) groups.push(...data.dictionaries);
                }
            }),
        );
        if (current !== item) return;
        knowMeaning.replaceChildren();
        if (groups.length) appendDictionaries(knowMeaning, groups);
        else knowMeaning.textContent = "No translation found.";
    }
    // Peek at the translation before self-assessing (as on the lexicon check
    // page): toggles the blur, records nothing, the Know/Don't-know buttons
    // stay. The button itself stays put so the same key/click hides it again.
    function knowShowTranslation() {
        if (!current || current.type !== "know" || current.pendingResponse) {
            return;
        }
        const stillBlurred = knowMeaning.classList.toggle("blurred");
        knowShowLabel.textContent = stillBlurred
            ? "Show translation"
            : "Hide translation";
    }
    async function knowSelfAssess(knows) {
        if (!current || current.type !== "know" || current.pendingResponse) {
            return;
        }
        current.pendingResponse = knows ? "y" : "n";
        knowAnswers.hidden = true;
        knowShowBar.hidden = true;
        knowMeaning.classList.remove("blurred");
        await postAnswer(current.word, current.pendingResponse);
        const item = current;
        if (current !== item) return;
        knowContinueBar.hidden = false;
        knowContinue.focus();
        void playWordAudio(item.word);
    }

    // Choice: pick the right translation among several.
    function renderChoice() {
        showBox("choice");
        status.textContent = "";
        undoBar.hidden = history.length === 0;
        if (history.length) {
            undoWord.textContent = history[history.length - 1].word;
        }
        choiceWord.textContent = current.word;
        choiceContinueBar.hidden = true;
        choiceOptions.replaceChildren();
        current.answered = false;
        current.options.forEach((option, index) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "option";
            button.dataset.key = String(index + 1);
            button.textContent = option;
            button.addEventListener("click", () => chooseOption(option));
            choiceOptions.append(button);
        });
        presentedAt = Date.now();
    }
    async function chooseOption(option) {
        if (!current || current.type !== "choice" || current.answered) return;
        current.answered = true;
        for (const button of choiceOptions.querySelectorAll("button")) {
            button.disabled = true;
            if (button.textContent === current.answer) {
                button.classList.add("correct");
            } else if (button.textContent === option) {
                button.classList.add("wrong");
            }
        }
        await postAnswer(current.word, option === current.answer ? "y" : "n");
        choiceContinueBar.hidden = false;
        choiceContinue.focus();
        void playWordAudio(current.word);
    }

    // Connect: match each word (left) with its translation (right). A word is
    // recorded right unless it was part of a wrong attempt.
    function renderConnect() {
        showBox("connect");
        status.textContent = "";
        undoBar.hidden = true; // Several answers at once; undo is per-record.
        connectContinueBar.hidden = true;
        connectWords.replaceChildren();
        connectTranslations.replaceChildren();
        current.selected = null;
        current.matched = 0;
        current.wrong = {};
        for (const pair of current.pairs) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "connect-cell";
            button.dataset.word = pair.word;
            button.textContent = pair.word;
            button.addEventListener("click", () => connectSelectWord(button));
            connectWords.append(button);
        }
        const shuffled = current.pairs.map((pair) => pair.translation);
        for (let i = shuffled.length - 1; i > 0; i -= 1) {
            const j = Math.floor(Math.random() * (i + 1));
            [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
        }
        for (const text of shuffled) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "connect-cell";
            button.dataset.translation = text;
            button.textContent = text;
            button.addEventListener("click", () =>
                connectSelectTranslation(button, text),
            );
            connectTranslations.append(button);
        }
        presentedAt = Date.now();
    }
    function connectSelectWord(button) {
        if (button.disabled) return;
        if (current.selected) current.selected.classList.remove("selected");
        current.selected = button;
        button.classList.add("selected");
    }
    async function connectSelectTranslation(button, translation) {
        if (button.disabled || !current || !current.selected) return;
        const word = current.selected.dataset.word;
        const pair = current.pairs.find((p) => p.word === word);
        if (pair && pair.translation === translation) {
            current.selected.disabled = true;
            current.selected.classList.remove("selected");
            current.selected.classList.add("matched");
            button.disabled = true;
            button.classList.add("matched");
            current.selected = null;
            current.matched += 1;
            await postAnswer(word, current.wrong[word] ? "n" : "y");
            if (current.matched === current.pairs.length) {
                connectContinueBar.hidden = false;
                connectContinue.focus();
            }
        } else {
            current.wrong[word] = true;
            button.classList.add("wrong-flash");
            setTimeout(() => button.classList.remove("wrong-flash"), 350);
        }
    }

    // Show the example sentence (word blanked) and one of its translations,
    // both kept off `/next` so the card appears immediately.
    function renderSentence() {
        sentence.replaceChildren();
        sentenceTranslation.replaceChildren();
        sentenceTranslation.hidden = true;
        if (!current || !current.sentence) {
            sentence.hidden = true;
            return;
        }
        sentence.hidden = false;
        sentence.textContent = "···";
        const item = current;
        item.sentence.then((data) => {
            if (current !== item) return;
            if (data && data.html) {
                sentence.innerHTML = data.html; // Safe fragment, word blanked.
                if (data.translation) {
                    sentenceTranslation.textContent = data.translation;
                    sentenceTranslation.hidden = false;
                }
            } else {
                sentence.textContent = "—";
            }
        });
    }

    function renderExternalLinks() {
        if (!current) {
            externalLinks.hidden = true;
            return;
        }
        const encoded = encodeURIComponent(current.word);
        const langName = languageName(language);
        const query = `Translate ${langName} word "${current.word}".`;
        googleLink.href =
            `https://www.google.com/search?q=${encodeURIComponent(query)}`;
        yandexLink.href =
            `https://translate.yandex.ru/?source_lang=${encodeURIComponent(language)}` +
            `&target_lang=en&text=${encoded}`;
        wiktionaryLink.href =
            `https://en.wiktionary.org/wiki/${encoded}` +
            `#${encodeURIComponent(langName.replace(/ /g, "_"))}`;
        const lower = current.word.toLowerCase();
        kaikkiLink.href =
            `https://kaikki.org/dictionary/${encodeURIComponent(langName)}/meaning/` +
            `${encodeURIComponent(lower.slice(0, 1))}/` +
            `${encodeURIComponent(lower.slice(0, 2))}/` +
            `${encodeURIComponent(lower)}.html`;
        externalLinks.hidden = false;
    }

    // Record one word's answer, carrying the current question's type and (for
    // type_word) the example shown and the time taken as provenance.
    async function postAnswer(word, response) {
        if (current && current.source === "new") handledNew.add(word);
        history.push({ word });
        await api(`${base}/answer`, {
            method: "POST",
            body: {
                word,
                response,
                question_type: current ? current.type : "type_word",
                sentence_id: current ? current.sentenceId ?? null : null,
                seconds: presentedAt ? (Date.now() - presentedAt) / 1000 : null,
            },
        });
    }

    // type_word answer. "I don't know" first reveals the word (the meaning is
    // already shown); a second action (Continue) records the wrong answer.
    async function recordTyped(response) {
        if (!current || current.type !== "type_word") return;
        if (response === "n" && !answeredWrong) {
            answeredWrong = true;
            wordEl.textContent = current.word;
            input.hidden = true;
            answers.hidden = true;
            continueBar.hidden = false;
            continueButton.focus();
            void playWordAudio(current.word); // Hear it once revealed.
            return;
        }
        if (response === "y") void playWordAudio(current.word); // Got it right.
        await postAnswer(current.word, response);
        await advance();
    }

    // Remove the most recent answer and re-present that word as a type_word
    // question to re-answer it.
    async function undo() {
        if (history.length === 0) return;
        const response = await api(`${base}/undo`, { method: "POST" });
        if (!response.ok) return;
        const { word: undone } = await response.json();
        if (!undone) return;
        history.pop();
        current = makeItem({ word: undone, source: "review" });
        renderCardStatus(null); // The word's history changed server-side.
        renderTeach();
    }

    // The new-word check: record know/don't-know in the `ask_lexicon`. "Know"
    // skips learning the word; "don't know" admits it and teaches it now.
    async function askAnswer(knows) {
        if (!current || !current.checkLexicon) return;
        const item = current;
        handledNew.add(item.word);
        await api(
            `/me/lexicons/${encodeURIComponent(item.checkLexicon)}/answer`,
            {
                method: "POST",
                body: { word: item.word, response: knows ? "know" : "dont" },
            },
        );
        if (knows) {
            await advance();
        } else {
            item.checkLexicon = null;
            current = item;
            renderTeach();
        }
    }

    // type_word: "I don't know" / "Skip" buttons and the reveal Continue.
    for (const button of answers.querySelectorAll("button")) {
        button.addEventListener("click", () =>
            recordTyped(button.dataset.response),
        );
    }
    continueButton.addEventListener("click", () => recordTyped("n"));
    // know: self-assess, then Continue advances.
    for (const button of knowAnswers.querySelectorAll("button")) {
        button.addEventListener("click", () =>
            knowSelfAssess(button.dataset.response === "y"),
        );
    }
    knowShow.addEventListener("click", () => void knowShowTranslation());
    knowContinue.addEventListener("click", advance);
    // choice / connect: Continue advances once the question is answered.
    choiceContinue.addEventListener("click", advance);
    connectContinue.addEventListener("click", advance);
    document.getElementById("undo").addEventListener("click", undo);
    document
        .getElementById("ask-know")
        .addEventListener("click", () => askAnswer(true));
    document
        .getElementById("ask-dont")
        .addEventListener("click", () => askAnswer(false));

    // On-screen buttons for letters of the learning language that the user's
    // physical keyboard may lack.
    function renderSymbolButtons(symbols) {
        symbolButtons.replaceChildren();
        symbolButtons.hidden = symbols.length === 0;
        for (const symbol of symbols) {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = symbol;
            // Keep the focus (and thus the caret) in the input: mousedown
            // would move it to the button before click fires.
            button.addEventListener("mousedown", (event) =>
                event.preventDefault(),
            );
            button.addEventListener("click", () => {
                if (input.hidden || input.disabled) return;
                const start = input.selectionStart ?? input.value.length;
                const end = input.selectionEnd ?? start;
                input.setRangeText(symbol, start, end, "end");
                input.focus();
                input.dispatchEvent(new Event("input"));
            });
            symbolButtons.append(button);
        }
    }

    // type_word: auto-accept the instant the typed text matches an accepted form.
    input.addEventListener("input", () => {
        if (!current || current.type !== "type_word") return;
        if ((current.accepted || []).includes(input.value)) {
            void recordTyped("y");
        }
    });

    // Keyboard: while typing, only Escape (give up) is a shortcut — letters go
    // to the field; otherwise a visible button's `data-key` triggers it.
    function shortcutButton(event) {
        if (event.ctrlKey || event.metaKey || event.altKey) return null;
        if (event.target === input || event.target.matches("textarea, select")) {
            return null;
        }
        let key;
        if (event.key === " ") key = " ";
        else if (event.key === "Enter") key = "enter";
        else key = event.key.toLowerCase();
        return (
            [...document.querySelectorAll(`button[data-key="${key}"]`)].find(
                (candidate) => !candidate.hidden && candidate.offsetParent,
            ) || null
        );
    }
    function isTypingEscape(event) {
        return (
            event.target === input &&
            event.key === "Escape" &&
            !event.ctrlKey &&
            !event.metaKey &&
            !event.altKey
        );
    }
    // Act on key *release*, so a held key can't rifle through several cards (see
    // the lexicon session). keydown arms the key and suppresses its default;
    // keyup fires it once. Arming only on a valid press means releasing the last
    // letter of a typed word never triggers the next card's shortcut.
    const armedKeys = new Set();
    document.addEventListener("keydown", (event) => {
        if (isTypingEscape(event) || shortcutButton(event)) {
            event.preventDefault();
            armedKeys.add(event.code);
        }
    });
    document.addEventListener("keyup", (event) => {
        if (!armedKeys.delete(event.code)) return;
        if (isTypingEscape(event)) {
            event.preventDefault();
            void recordTyped("n");
            return;
        }
        const button = shortcutButton(event);
        if (!button) return;
        event.preventDefault();
        button.classList.add("pressed");
        setTimeout(() => button.classList.remove("pressed"), 120);
        button.click();
    });

    status.textContent = "Loading…";
    const [dictionariesResponse, settingsResponse] = await Promise.all([
        api(`${base}/dictionaries`),
        api(`${base}/settings`),
    ]);
    if (dictionariesResponse.ok) dictionaries = await dictionariesResponse.json();
    if (settingsResponse.ok) {
        const settings = await settingsResponse.json();
        playAudio = settings.play_audio;
        renderSymbolButtons(settings.extra_symbols || "");
        knowWord.className =
            settings.learning_type === "symbol" ? "symbol" : "word";
    }
    await advance();
}

// Learning repetition page.

export async function initLearn() {
    requireAuth();
    const id = new URLSearchParams(location.search).get("learning");
    document
        .getElementById("learn-heading")
        .replaceChildren("Learn: ", identifierSpan(id));
    await runLearnSession(`/me/learnings/${encodeURIComponent(id)}`);
}
