// The "add a learning" form, presented as a sheet from a course's detail
// screen.
//
// The course's language is fixed; this form only picks translation targets
// (`/translation-languages`, English preselected) and submits to
// `/me/courses/{course_id}/learnings`. The server assembles the learning's
// configuration (frequency list, dictionaries, sentences, audio) itself.

import EmmioKit
import SwiftUI

struct CreateLearningView: View {
    let courseId: String

    /// Called with the fresh learning's id after a successful creation (the
    /// sheet dismisses itself).
    let onCreated: (String) async -> Void

    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    @State private var targets: [String] = []
    @State private var selectedTargets: Set<String> = ["en"]
    @State private var isLoading = true
    @State private var isCreating = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Group {
                if isLoading {
                    ProgressView()
                } else {
                    form
                }
            }
            .navigationTitle("New Learning")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Create") { create() }
                        .disabled(
                            isLoading || isCreating || selectedTargets.isEmpty
                        )
                }
            }
            .task { await load() }
        }
    }

    private var form: some View {
        Form {
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
            targets = try await model.client.translationLanguages()
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
                let learningId = try await model.client.createLearning(
                    courseId: courseId,
                    translationLanguages: targets.filter(
                        selectedTargets.contains
                    )
                )
                dismiss()
                await onCreated(learningId)
            } catch {
                self.error = message(for: error)
            }
        }
    }

    /// A language's display name in the UI language, e.g. `fr` → "French".
    private func name(of code: String) -> String {
        Locale.current.localizedString(forLanguageCode: code) ?? code
    }

    /// The server explains creation failures (no valid target) in the 400
    /// body's `detail`; show that over the generic line.
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
