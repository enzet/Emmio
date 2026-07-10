// App-wide state: the API client, the stored server URL and token, and the
// auth gate the root view switches on. A `@MainActor` `ObservableObject` so
// SwiftUI observes it directly; the actual networking hops to `EmmioClient`
// (an actor) via `async` calls.
//
// The token and base URL persist in `UserDefaults` for a simple first version.
// A shipping app should keep the token in the Keychain instead — see README.

import EmmioKit
import Foundation

@MainActor
final class AppModel: ObservableObject {
    private enum Keys {
        static let token = "emmio.token"
        static let baseURL = "emmio.baseURL"
    }

    /// Default API origin for local development (`uvicorn` on port 8000).
    static let defaultBaseURL = "http://localhost:8000"

    @Published private(set) var isAuthenticated: Bool
    @Published var baseURLString: String

    private(set) var client: EmmioClient

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let base = defaults.string(forKey: Keys.baseURL) ?? Self.defaultBaseURL
        let token = defaults.string(forKey: Keys.token)
        self.baseURLString = base
        self.isAuthenticated = token != nil
        self.client = EmmioClient(
            baseURL: URL(string: base) ?? URL(string: Self.defaultBaseURL)!,
            token: token
        )
    }

    private let defaults: UserDefaults

    /// Rebuild the client against a new server URL (from the login screen).
    func updateBaseURL(_ string: String) {
        let trimmed = string.trimmingCharacters(in: .whitespaces)
        guard let url = URL(string: trimmed) else { return }
        baseURLString = trimmed
        defaults.set(trimmed, forKey: Keys.baseURL)
        client = EmmioClient(baseURL: url)
        isAuthenticated = false
        defaults.removeObject(forKey: Keys.token)
    }

    /// Log in and persist the token, flipping the app to the authenticated UI.
    func logIn(email: String, password: String) async throws {
        let token = try await client.logIn(email: email, password: password)
        defaults.set(token.accessToken, forKey: Keys.token)
        isAuthenticated = true
    }

    /// Forget the token and return to the login screen.
    func logOut() async {
        await client.setToken(nil)
        defaults.removeObject(forKey: Keys.token)
        isAuthenticated = false
    }
}
