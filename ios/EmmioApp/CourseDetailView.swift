// A course's learnings, each opening a learning session, plus a sheet to add
// a new one.

import EmmioKit
import SwiftUI

struct CourseDetailView: View {
    let course: CourseSummary

    @EnvironmentObject private var model: AppModel

    @State private var learnings: [LearningSummary] = []
    @State private var error: String?
    @State private var isLoading = false
    @State private var isCreating = false

    var body: some View {
        List {
            if let error {
                Text(error).foregroundStyle(.red)
            }
            ForEach(learnings) { learning in
                NavigationLink(value: learning) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(learning.name).font(.headline)
                        Text("\(learning.words) words · \(learning.answers) answers")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .overlay {
            if isLoading && learnings.isEmpty { ProgressView() }
            if !isLoading && learnings.isEmpty && error == nil {
                ContentUnavailableView(
                    "No learnings yet",
                    systemImage: "book",
                    description: Text("Tap + to add one, e.g. vocabulary.")
                )
            }
        }
        .navigationTitle(course.name)
        .navigationDestination(for: LearningSummary.self) { learning in
            LearnView(learning: learning)
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("Add Learning", systemImage: "plus") {
                    isCreating = true
                }
            }
        }
        .sheet(isPresented: $isCreating) {
            CreateLearningView(courseId: course.courseId) { _ in await load() }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        isLoading = true
        error = nil
        defer { isLoading = false }
        do {
            learnings = try await model.client.courseDetail(
                courseId: course.courseId
            ).learnings
        } catch {
            self.error = friendlyMessage(for: error)
        }
    }
}
