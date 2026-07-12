// The "add a course" form, presented as a sheet from the course list.
//
// Mirrors the web app's create-course form: the language selector offers the
// languages available for learning (`/lexicon-languages` — those with a
// frequency list to draw new words from and Tatoeba sentences for examples),
// the translation targets come from `/translation-languages` (English
// preselected), and submitting posts to `/me/courses`. The server assembles
// the course configuration itself.

import EmmioKit
import SwiftUI

struct CreateCourseView: View {
    /// Called with the fresh course's id after a successful creation (the
    /// sheet dismisses itself).
    let onCreated: (String) async -> Void

    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    @State private var languages: [String] = []
    @State private var targets: [String] = []
    @State private var language = ""
    @State private var selectedTargets: Set<String> = ["en"]
    @State private var isLoading = true
    @State private var isCreating = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Group {
                if isLoading {
                    ProgressView()
                } else if languages.isEmpty {
                    ContentUnavailableView(
                        "No languages available",
                        systemImage: "globe",
                        description: Text(
                            "The server offers no language with both a "
                                + "frequency list and example sentences yet."
                        )
                    )
                } else {
                    form
                }
            }
            .navigationTitle("New Course")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Create") { create() }
                        .disabled(
                            isLoading || isCreating
                                || language.isEmpty || selectedTargets.isEmpty
                        )
                }
            }
            .task { await load() }
        }
    }

    private var form: some View {
        Form {
            Picker("Language", selection: $language) {
                ForEach(languages, id: \.self) { code in
                    Text(name(of: code)).tag(code)
                }
            }
            Section("Translate into") {
                ForEach(targets, id: \.self) { code in
                    Button {
                        toggle(code)
                    } label: {
                        HStack {
                            Text(name(of: code)).foregroundStyle(.primary)
                            Spacer()
                            if selectedTargets.contains(code) {
                                Image(systemName: "checkmark")
                            }
                        }
                    }
                }
            }
            if let error {
                Text(error).foregroundStyle(.red)
            }
            if isCreating {
                HStack(spacing: 8) {
                    ProgressView()
                    Text("Creating…").foregroundStyle(.secondary)
                }
            }
        }
    }

    // MARK: - Operations

    private func load() async {
        defer { isLoading = false }
        do {
            async let available = model.client.lexiconLanguages()
            async let translations = model.client.translationLanguages()
            languages = try await available
            targets = try await translations
            language = languages.first ?? ""
        } catch {
            self.error = friendlyMessage(for: error)
        }
    }

    private func toggle(_ code: String) {
        if selectedTargets.contains(code) {
            selectedTargets.remove(code)
        } else {
            selectedTargets.insert(code)
        }
    }

    private func create() {
        guard !isCreating else { return }
        isCreating = true
        error = nil
        Task {
            defer { isCreating = false }
            do {
                // Keep the server's offer order for the selected targets.
                let courseId = try await model.client.createCourse(
                    language: language,
                    translationLanguages: targets.filter(
                        selectedTargets.contains
                    )
                )
                dismiss()
                await onCreated(courseId)
            } catch {
                self.error = message(for: error)
            }
        }
    }

    /// A language's display name in the UI language, e.g. `fr` → "French".
    private func name(of code: String) -> String {
        Locale.current.localizedString(forLanguageCode: code) ?? code
    }

    /// The server explains creation failures (no frequency list, no valid
    /// target) in the 400 body's `detail`; show that over the generic line.
    private func message(for error: Error) -> String {
        if case let EmmioError.http(400, body) = error,
            let data = body.data(using: .utf8),
            let json = try? JSONSerialization.jsonObject(with: data)
                as? [String: Any],
            let detail = json["detail"] as? String
        {
            return detail
        }
        return friendlyMessage(for: error)
    }
}
