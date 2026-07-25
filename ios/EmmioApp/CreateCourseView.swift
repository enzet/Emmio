// The "add a course" form, presented as a sheet from the course list.
//
// A course is just a language-level shell (mirrors the web app's simplified
// create-course form): the language selector offers the languages available
// for learning (`/lexicon-languages` — those with a frequency list to draw
// new words from and Tatoeba sentences for examples), and submitting posts
// to `/me/courses`. A learning is added to it afterward, on the course's
// detail screen.

import EmmioKit
import SwiftUI

struct CreateCourseView: View {
    /// Called with the fresh course's id after a successful creation (the
    /// sheet dismisses itself).
    let onCreated: (String) async -> Void

    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    @State private var languages: [String] = []
    @State private var language = ""
    @State private var name = ""
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
                        .disabled(isLoading || isCreating || language.isEmpty)
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
            TextField("Name (optional)", text: $name)
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
            languages = try await model.client.lexiconLanguages()
            language = languages.first ?? ""
        } catch {
            self.error = friendlyMessage(for: error)
        }
    }

    private func create() {
        guard !isCreating else { return }
        isCreating = true
        error = nil
        Task {
            defer { isCreating = false }
            do {
                let trimmedName = name.trimmingCharacters(
                    in: .whitespacesAndNewlines
                )
                let courseId = try await model.client.createCourse(
                    language: language,
                    name: trimmedName.isEmpty ? name(of: language) : trimmedName
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

    /// The server explains creation failures in the 4xx body's `detail`; show
    /// that over the generic line.
    private func message(for error: Error) -> String {
        if case let EmmioError.http(status, body) = error, (400..<500).contains(status),
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
