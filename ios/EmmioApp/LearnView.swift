// The learning session for one course.
//
// Driven by `.../question`, which chooses each question's type server-side
// (know / choice / connect / type_word) and returns its grading key. This view
// fetches a question, renders the matching card, lets the card grade the answer
// client-side (mirroring `web/app.js`) and record it via `.../answer`, then
// advances. `type == nil` ends the session. Undo re-presents the freed word as
// a type_word card.
//
// Not yet handled (see README): new-word intake (`/new`), example sentences,
// and pronunciation audio.

import EmmioKit
import SwiftUI

/// The parent-owned operations a question card performs: record an answer, look
/// up a word's meaning, and advance to the next question. Bundled so cards take
/// one value instead of several closures.
struct LearnActions {
    /// Record one word's answer (updates undo history, then POSTs).
    let record: (String, LearnResponse, QuestionType, Double) async -> Void
    /// A word's meaning as plain text (`hideWord` blanks the word out); `""`
    /// when none is found.
    let meaning: (String, Bool) async -> String
    /// Fetch and present the next question (or finish).
    let advance: () async -> Void
}

struct LearnView: View {
    let course: CourseSummary

    @EnvironmentObject private var model: AppModel

    private enum Phase: Equatable {
        case loading
        case active
        case done
        case failed(String)
    }

    @State private var phase: Phase = .loading
    @State private var question: Question?
    @State private var language = ""
    @State private var history: [String] = []
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
                    description: Text("Nothing due right now.")
                )
            case .active:
                if let question, let kind = question.kind {
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
        .navigationTitle(course.name)
        .navigationBarTitleDisplayMode(.inline)
        .task { await advance() }
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
            TypeWordCard(question: question, actions: actions)
        }
    }

    private var actions: LearnActions {
        LearnActions(
            record: { word, response, type, seconds in
                await record(word, response, type, seconds)
            },
            meaning: { word, hideWord in await meaning(word, hideWord: hideWord) },
            advance: { await advance() }
        )
    }

    // MARK: - Operations

    private func record(
        _ word: String, _ response: LearnResponse,
        _ type: QuestionType, _ seconds: Double
    ) async {
        history.append(word)
        do {
            try await model.client.answer(
                courseId: course.courseId, word: word,
                response: response, questionType: type, seconds: seconds
            )
        } catch {
            phase = .failed(friendlyMessage(for: error))
        }
    }

    private func meaning(_ word: String, hideWord: Bool) async -> String {
        guard let translation = try? await model.client.translation(
            courseId: course.courseId, word: word, hideWord: hideWord
        ) else { return "" }
        return translation.dictionaries
            .map { HTMLText.plain(from: $0.html) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n\n")
    }

    private func advance() async {
        phase = .loading
        do {
            let next = try await model.client.question(courseId: course.courseId)
            if next.kind == nil {
                question = nil
                phase = .done
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

    private func undo() async {
        do {
            guard let word = try await model.client.undo(
                courseId: course.courseId
            ) else { return }
            if !history.isEmpty { history.removeLast() }
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
        Task {
            await actions.record(
                word, response, .know, Date().timeIntervalSince(presentedAt)
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
        let response: LearnResponse = option == answer ? .right : .wrong
        Task {
            await actions.record(
                word, response, .choice, Date().timeIntervalSince(presentedAt)
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

/// Production: read the meaning, type the word.
private struct TypeWordCard: View {
    let question: Question
    let actions: LearnActions

    @State private var typed = ""
    @State private var revealed = false  // After "I don't know".
    @State private var prompt = ""
    @State private var busy = false
    @State private var presentedAt = Date()

    private var word: String { question.words.first ?? "" }
    private var accepted: [String] { question.accepted ?? [word] }

    var body: some View {
        VStack(spacing: 20) {
            Text("Type the word").font(.headline)
            if !prompt.isEmpty {
                ScrollView {
                    Text(prompt).frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: 180)
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
        }
    }

    private func finish(_ response: LearnResponse) {
        guard !busy else { return }
        busy = true
        Task {
            await actions.record(
                word, response, .typeWord, Date().timeIntervalSince(presentedAt)
            )
            await actions.advance()
        }
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
            Task { await actions.record(word, response, .connect, seconds) }
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
