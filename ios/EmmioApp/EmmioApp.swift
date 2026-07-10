// App entry point and the auth gate: the login screen until a token is stored,
// the course list once authenticated.

import SwiftUI

@main
struct EmmioApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            NavigationStack {
                if model.isAuthenticated {
                    CourseListView()
                } else {
                    LoginView()
                }
            }
            .environmentObject(model)
        }
    }
}
