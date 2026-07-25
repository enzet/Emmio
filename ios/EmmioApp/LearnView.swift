// The learning session for one learning.
//
// Due reviews come first, driven by `.../question`, which chooses each
// question's type server-side (know / choice / connect / type_word) and
// returns its grading key. This view fetches a question, renders the matching
// card, lets the card grade the answer client-side (mirroring `web/app.js`)
// and record it via `.../answer`, then advances. Undo re-presents the freed
// word as a type_word card.
//
// When nothing is due (`type == nil`), new words are drawn from `.../new`:
// each is taught as a type_word card, possibly after a know/don't-know check
// recorded in the learning's ask lexicon ("know" skips the word, "don't know"
// admits it). The session ends when `/new` also has nothing left.
//
// type_word cards also show a blanked example sentence with its translation
// (`.../sentence`, the example's id recorded with the answer), and the word's
// pronunciation (`.../audio`) plays best-effort once the answer is known:
// on the know reveal, the choice pick, and a typed word's success or reveal.

import AVFoundation
import EmmioKit
import SwiftUI

/// Plays pronunciation recordings, retaining the `AVAudioPlayer` (playback
/// stops when the player is released) and cutting off the previous word's.
@MainActor
final class AudioPlayer {
    private var player: AVAudioPlayer?

    init() {
        // Pronunciation should sound even with the ring/silent switch off
        // (the default `.soloAmbient` category is muted by it).
        try? AVAudioSession.sharedInstance().setCategory(.playback)
    }

    func play(_ data: Data) {
        player?.stop()
        player = try? AVAudioPlayer(data: data)
        player?.play()
    }
}

/// The parent-owned operations a question card performs: record an answer, look
/// up a word's meaning, and advance to the next question. Bundled so cards take
/// one value instead of several closures.
struct LearnActions {
    /// Record one word's answer (updates undo history, then POSTs). The `Int?`
    /// is the id of the example sentence shown, stored as provenance.
    let record: (String, LearnResponse, QuestionType, Int?, Double) async -> Void
    /// A word's meaning as plain text (`hideWord` blanks the word out); `""`
    /// when none is found.
    let meaning: (String, Bool) async -> String
    /// An example sentence for a word (blanked, with a translation), or `nil`
    /// when the learning has none.
    let sentence: (String) async -> Sentence?
    /// Play the word's pronunciation, if any. Fire-and-forget: returns at
    /// once, and missing audio is silently ignored.
    let playAudio: (String) -> Void
    /// Fetch and present the next question (or finish).
    let advance: () async -> Void
}

struct LearnView: View {
    let learning: LearningSummary

    @EnvironmentObject private var model: AppModel

    private enum Phase: Equatable {
        case loading
        case active
        case done
        case failed(String)
    }

    /// A new word awaiting its know/don't-know pre-check (`check_lexicon`
    /// from `/new`), presented as an `AskCard` instead of a question card.
    private struct NewWordCheck {
        let word: String
        let accepted: [String]
        let lexiconId: String
    }

    @State private var phase: Phase = .loading
    @State private var question: Question?
    @State private var check: NewWordCheck?
    /// Whether the presented question teaches a new word from `/new` (rather
    /// than reviewing a due one).
    @State private var isNewWord = false
    /// New words already decided this session (answered or admitted), excluded
    /// from `/new` because the stateless server would return them again.
    @State private var handledNew: Set<String> = []
    /// `/new` returned no word; stop asking for the rest of the session.
    @State private var newExhausted = false
    @State private var language = ""
    @State private var history: [String] = []
    @State private var audioPlayer = AudioPlayer()
    /// The open learning session on the server, grouping this screen's
    /// answers into one log row. `nil` when opening failed — answers are
    /// still recorded, just not grouped.
    @State private var sessionId: String?
    /// Bumped per presented question so each card gets a fresh identity (and so
    /// its local state — typed text, selection — resets between questions).
    @State private var seq = 0

    var body: some View {
        VStack(spacing: 20) {
            switch phase {
            case .loading:
                ProgressView().frame(maxHeight: .infinity)
            case .failed(let message):
                ContentUnavailableView(
                    "Something went wrong",
                    systemImage: "exclamationmark.triangle",
                    description: Text(message)
                )
            case .done:
                ContentUnavailableView(
                    "All caught up",
                    systemImage: "checkmark.circle",
                    description: Text(
                        "No reviews due and no new words right now."
                    )
                )
            case .active:
                if let check {
                    AskCard(word: check.word) { knows in
                        await decide(check, knows: knows)
                    }
                    .id(seq)
                } else if let question, let kind = question.kind {
                    card(for: question, kind: kind).id(seq)
                }
            }

            if !history.isEmpty {
                Button("Undo last (\(history.last ?? ""))") {
                    Task { await undo() }
                }
                .font(.footnote)
            }
        }
        .padding()
        .navigationTitle(learning.name)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            // `/question` refines this per question; `/new` sends no language,
            // so start from the learning's.
            language = learning.learningLanguage
            sessionId = try? await model.client.openLearningSession(
                learningId: learning.learningId
            )
            await advance()
        }
        .onDisappear {
            guard let sessionId else { return }
            let client = model.client
            let learningId = learning.learningId
            Task {
                try? await client.closeLearningSession(
                    learningId: learningId, sessionId: sessionId
                )
            }
        }
    }

    @ViewBuilder
    private func card(for question: Question, kind: QuestionType) -> some View {
        switch kind {
        case .know:
            KnowCard(question: question, actions: actions)
        case .choice:
            ChoiceCard(question: question, actions: actions)
        case .connect:
            ConnectCard(question: question, actions: actions)
        case .typeWord:
            TypeWordCard(
                question: question, actions: actions, isNew: isNewWord
            )
        }
    }

    private var actions: LearnActions {
        LearnActions(
            record: { word, response, type, sentenceId, seconds in
                await record(word, response, type, sentenceId, seconds)
            },
            meaning: { word, hideWord in await meaning(word, hideWord: hideWord) },
            sentence: { word in await sentence(for: word) },
            playAudio: { word in playAudio(word) },
            advance: { await advance() }
        )
    }

    // MARK: - Operations

    private func record(
        _ word: String, _ response: LearnResponse,
        _ type: QuestionType, _ sentenceId: Int?, _ seconds: Double
    ) async {
        history.append(word)
        if isNewWord { handledNew.insert(word) }
        do {
            try await model.client.answer(
                learningId: learning.learningId, word: word,
                response: response, questionType: type,
                sentenceId: sentenceId, sessionId: sessionId,
                seconds: seconds
            )
        } catch {
            phase = .failed(friendlyMessage(for: error))
        }
    }

    private func meaning(_ word: String, hideWord: Bool) async -> String {
        guard let translation = try? await model.client.translation(
            learningId: learning.learningId, word: word, hideWord: hideWord
        ) else { return "" }
        return translation.dictionaries
            .map { HTMLText.plain(from: $0.html) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n\n")
    }

    private func sentence(for word: String) async -> Sentence? {
        guard let sentence = try? await model.client.sentence(
            learningId: learning.learningId, word: word
        ), sentence.sentence != nil else { return nil }
        return sentence
    }

    /// Fetch and play the word's pronunciation, ignoring failures (no
    /// recording, audio disabled for the learning, or a network error).
    private func playAudio(_ word: String) {
        Task {
            guard let data = ((try? await model.client.audio(
                learningId: learning.learningId, word: word
            )) ?? nil) else { return }
            audioPlayer.play(data)
        }
    }

    private func advance() async {
        phase = .loading
        check = nil
        isNewWord = false
        do {
            let next = try await model.client.question(learningId: learning.learningId)
            if next.kind == nil {
                question = nil
                await advanceToNew()
            } else {
                question = next
                language = next.language
                seq += 1
                phase = .active
            }
        } catch {
            phase = .failed(friendlyMessage(for: error))
        }
    }

    /// Present the next new word from `/new` — its lexicon check first when
    /// one is requested — or finish the session when none remains.
    private func advanceToNew() async {
        if !newExhausted {
            let new: NewQuestion
            do {
                new = try await model.client.newWord(
                    learningId: learning.learningId,
                    exclude: handledNew.sorted()
                )
            } catch {
                phase = .failed(friendlyMessage(for: error))
                return
            }
            if let word = new.word {
                if let lexiconId = new.checkLexicon {
                    check = NewWordCheck(
                        word: word,
                        accepted: new.accepted ?? [word],
                        lexiconId: lexiconId
                    )
                    seq += 1
                    phase = .active
                } else {
                    teach(word: word, accepted: new.accepted ?? [word])
                }
                return
            }
            newExhausted = true
        }
        phase = .done
    }

    /// Present a new word as a type_word card to learn it now.
    private func teach(word: String, accepted: [String]) {
        check = nil
        isNewWord = true
        question = Question(
            type: QuestionType.typeWord.rawValue,
            language: language,
            words: [word],
            accepted: accepted
        )
        seq += 1
        phase = .active
    }

    /// Resolve a new word's know/don't-know check: record the answer in the
    /// ask lexicon, then skip the word ("know") or teach it ("don't know").
    private func decide(_ check: NewWordCheck, knows: Bool) async {
        handledNew.insert(check.word)
        do {
            try await model.client.answerLexicon(
                lexiconId: check.lexiconId,
                word: check.word,
                response: knows ? .know : .dont
            )
        } catch {
            phase = .failed(friendlyMessage(for: error))
            return
        }
        if knows {
            await advance()
        } else {
            teach(word: check.word, accepted: check.accepted)
        }
    }

    private func undo() async {
        do {
            guard let word = try await model.client.undo(
                learningId: learning.learningId
            ) else { return }
            if !history.isEmpty { history.removeLast() }
            check = nil
            isNewWord = false
            question = .typeWord(word: word, language: language)
            seq += 1
            phase = .active
        } catch {
            phase = .failed(friendlyMessage(for: error))
        }
    }
}

// MARK: - Cards

/// Recognition: see the word, self-assess, then the meaning is revealed.
private struct KnowCard: View {
    let question: Question
    let actions: LearnActions

    @State private var revealed = false
    @State private var meaning = ""
    @State private var busy = false
    @State private var presentedAt = Date()

    private var word: String { question.words.first ?? "" }

    var body: some View {
        VStack(spacing: 24) {
            Text("Do you know this word?").font(.headline)
            Text(word)
                .font(.system(size: 40, weight: .bold))
                .multilineTextAlignment(.center)

            if revealed {
                ScrollView {
                    Text(meaning.isEmpty ? "No translation found." : meaning)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .foregroundStyle(meaning.isEmpty ? .secondary : .primary)
                }
            }
            Spacer()

            if revealed {
                Button("Continue") { Task { await actions.advance() } }
                    .buttonStyle(.borderedProminent).controlSize(.large)
            } else {
                HStack(spacing: 16) {
                    Button("I don't", role: .destructive) { choose(.wrong) }
                        .buttonStyle(.bordered).controlSize(.large)
                        .frame(maxWidth: .infinity)
                    Button("I know it") { choose(.right) }
                        .buttonStyle(.borderedProminent).controlSize(.large)
                        .frame(maxWidth: .infinity)
                }
            }
        }
        .onAppear { presentedAt = Date() }
    }

    private func choose(_ response: LearnResponse) {
        guard !busy else { return }
        busy = true
        revealed = true
        actions.playAudio(word)
        Task {
            await actions.record(
                word, response, .know, nil, Date().timeIntervalSince(presentedAt)
            )
            meaning = await actions.meaning(word, false)
        }
    }
}

/// Pick the correct translation among several.
private struct ChoiceCard: View {
    let question: Question
    let actions: LearnActions

    @State private var answered = false
    @State private var picked: String?
    @State private var presentedAt = Date()

    private var word: String { question.words.first ?? "" }
    private var options: [String] { question.options ?? [] }
    private var answer: String { question.answer ?? "" }

    var body: some View {
        VStack(spacing: 20) {
            Text("Choose the translation").font(.headline)
            Text(word).font(.system(size: 34, weight: .bold))

            ForEach(options, id: \.self) { option in
                Button { choose(option) } label: {
                    Text(option).frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered).controlSize(.large)
                .tint(tint(for: option))
                .disabled(answered)
            }
            Spacer()

            if answered {
                Button("Continue") { Task { await actions.advance() } }
                    .buttonStyle(.borderedProminent).controlSize(.large)
            }
        }
        .onAppear { presentedAt = Date() }
    }

    private func choose(_ option: String) {
        guard !answered else { return }
        answered = true
        picked = option
        actions.playAudio(word)
        let response: LearnResponse = option == answer ? .right : .wrong
        Task {
            await actions.record(
                word, response, .choice, nil,
                Date().timeIntervalSince(presentedAt)
            )
        }
    }

    /// Green for the correct option, red for a wrong pick, default otherwise.
    private func tint(for option: String) -> Color? {
        guard answered else { return nil }
        if option == answer { return .green }
        if option == picked { return .red }
        return nil
    }
}

/// Production: read the meaning, type the word. With `isNew` the card teaches
/// a word drawn from `/new` rather than reviewing a due one.
private struct TypeWordCard: View {
    let question: Question
    let actions: LearnActions
    var isNew = false

    @State private var typed = ""
    @State private var revealed = false  // After "I don't know".
    @State private var prompt = ""
    @State private var sentence: Sentence?
    @State private var busy = false
    @State private var presentedAt = Date()

    private var word: String { question.words.first ?? "" }
    private var accepted: [String] { question.accepted ?? [word] }

    var body: some View {
        VStack(spacing: 20) {
            Text(isNew ? "New word — type it" : "Type the word")
                .font(.headline)
            if !prompt.isEmpty {
                ScrollView {
                    Text(prompt).frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: 180)
            }
            if let sentence, let html = sentence.sentence {
                VStack(spacing: 4) {
                    Text(HTMLText.plain(from: html))
                    if let translation = sentence.translation {
                        Text(translation).foregroundStyle(.secondary)
                    }
                }
                .font(.callout)
                .multilineTextAlignment(.center)
            }
            Text(revealed
                ? word : String(repeating: "_", count: word.count))
                .font(.system(
                    size: 30, weight: revealed ? .bold : .regular,
                    design: revealed ? .default : .monospaced
                ))

            if revealed {
                Button("Continue") { finish(.wrong) }
                    .buttonStyle(.borderedProminent).controlSize(.large)
            } else {
                TextField("Type the word", text: $typed)
                    .textFieldStyle(.roundedBorder)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .onChange(of: typed) { _, newValue in
                        if Grading.accepts(newValue, accepted: accepted) {
                            finish(.right)
                        }
                    }
                HStack(spacing: 16) {
                    Button("I don't know", role: .destructive) {
                        revealed = true
                        actions.playAudio(word)  // Hear it once revealed.
                    }
                    .buttonStyle(.bordered)
                    Button("Skip") { finish(.skip) }
                        .buttonStyle(.bordered)
                }
            }
            Spacer()
        }
        .onAppear {
            presentedAt = Date()
            Task { prompt = await actions.meaning(word, true) }
            Task { sentence = await actions.sentence(word) }
        }
    }

    private func finish(_ response: LearnResponse) {
        guard !busy else { return }
        busy = true
        if response == .right { actions.playAudio(word) }  // Got it right.
        Task {
            await actions.record(
                word, response, .typeWord, sentence?.sentenceId,
                Date().timeIntervalSince(presentedAt)
            )
            await actions.advance()
        }
    }
}

/// The new-word pre-check: does the user already know this word? The answer
/// is recorded in the learning's ask lexicon; "know" skips the word, "don't
/// know" admits it to learning.
private struct AskCard: View {
    let word: String
    /// Handle the user's choice (`true` = knows the word already).
    let onAnswer: (Bool) async -> Void

    @State private var busy = false

    var body: some View {
        VStack(spacing: 24) {
            Text("New word — do you know it?").font(.headline)
            Text(word)
                .font(.system(size: 40, weight: .bold))
                .multilineTextAlignment(.center)
            Spacer()

            HStack(spacing: 16) {
                Button("I don't", role: .destructive) { choose(false) }
                    .buttonStyle(.bordered).controlSize(.large)
                    .frame(maxWidth: .infinity)
                Button("I know it") { choose(true) }
                    .buttonStyle(.borderedProminent).controlSize(.large)
                    .frame(maxWidth: .infinity)
            }
        }
    }

    private func choose(_ knows: Bool) {
        guard !busy else { return }
        busy = true
        Task { await onAnswer(knows) }
    }
}

/// Match each word (left) with its translation (right). A word is recorded
/// correct unless it was part of a wrong attempt.
private struct ConnectCard: View {
    let question: Question
    let actions: LearnActions

    @State private var selected: String?
    @State private var matched: Set<String> = []
    @State private var wrong: Set<String> = []
    @State private var shuffled: [String] = []
    @State private var presentedAt = Date()

    private var pairs: [ConnectPair] { question.pairs ?? [] }
    private var allMatched: Bool {
        !pairs.isEmpty && matched.count == pairs.count
    }

    var body: some View {
        VStack(spacing: 20) {
            Text("Connect the words").font(.headline)
            HStack(alignment: .top, spacing: 16) {
                VStack(spacing: 12) {
                    ForEach(pairs, id: \.word) { pair in
                        cell(
                            pair.word, tint: wordTint(pair.word),
                            disabled: matched.contains(pair.word)
                        ) { selectWord(pair.word) }
                    }
                }
                VStack(spacing: 12) {
                    ForEach(shuffled, id: \.self) { translation in
                        cell(
                            translation, tint: translationTint(translation),
                            disabled: isTranslationMatched(translation)
                        ) { pick(translation) }
                    }
                }
            }
            Spacer()

            if allMatched {
                Button("Continue") { Task { await actions.advance() } }
                    .buttonStyle(.borderedProminent).controlSize(.large)
            }
        }
        .onAppear {
            presentedAt = Date()
            if shuffled.isEmpty {
                shuffled = pairs.map(\.translation).shuffled()
            }
        }
    }

    private func cell(
        _ text: String, tint: Color?, disabled: Bool, action: @escaping () -> Void
    ) -> some View {
        Button(action: action) { Text(text).frame(maxWidth: .infinity) }
            .buttonStyle(.bordered).controlSize(.large)
            .tint(tint)
            .disabled(disabled)
    }

    private func selectWord(_ word: String) {
        guard !matched.contains(word) else { return }
        selected = word
    }

    private func pick(_ translation: String) {
        guard let word = selected,
            let pair = pairs.first(where: { $0.word == word })
        else { return }
        if pair.translation == translation {
            matched.insert(word)
            let response: LearnResponse = wrong.contains(word) ? .wrong : .right
            let seconds = Date().timeIntervalSince(presentedAt)
            selected = nil
            Task { await actions.record(word, response, .connect, nil, seconds) }
        } else {
            wrong.insert(word)
        }
    }

    private func isTranslationMatched(_ translation: String) -> Bool {
        pairs.contains {
            $0.translation == translation && matched.contains($0.word)
        }
    }

    private func wordTint(_ word: String) -> Color? {
        if matched.contains(word) { return .green }
        if selected == word { return .accentColor }
        return nil
    }

    private func translationTint(_ translation: String) -> Color? {
        isTranslationMatched(translation) ? .green : nil
    }
}
