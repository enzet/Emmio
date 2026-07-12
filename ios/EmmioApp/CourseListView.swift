// The authenticated home: the user's courses, each opening a learning
// session, plus a sheet to create a new one.

import EmmioKit
import SwiftUI

struct CourseListView: View {
    @EnvironmentObject private var model: AppModel

    @State private var courses: [CourseSummary] = []
    @State private var error: String?
    @State private var isLoading = false
    @State private var isCreating = false

    var body: some View {
        List {
            if let error {
                Text(error).foregroundStyle(.red)
            }
            ForEach(courses) { course in
                NavigationLink(value: course) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(course.name).font(.headline)
                        Text("\(course.words) words · \(course.answers) answers")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .overlay {
            if isLoading && courses.isEmpty { ProgressView() }
            if !isLoading && courses.isEmpty && error == nil {
                ContentUnavailableView(
                    "No courses",
                    systemImage: "book",
                    description: Text("Tap + to create your first course.")
                )
            }
        }
        .navigationTitle("Courses")
        .navigationDestination(for: CourseSummary.self) { course in
            LearnView(course: course)
        }
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button("Log Out") { Task { await model.logOut() } }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button("Add Course", systemImage: "plus") { isCreating = true }
            }
        }
        .sheet(isPresented: $isCreating) {
            CreateCourseView { _ in await load() }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        isLoading = true
        error = nil
        defer { isLoading = false }
        do {
            courses = try await model.client.courses()
        } catch {
            self.error = friendlyMessage(for: error)
        }
    }
}
