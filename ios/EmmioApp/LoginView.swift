// Email + password login, with an editable server URL so the same build can
// point at a local `uvicorn` or a deployed instance.

import EmmioKit
import SwiftUI

struct LoginView: View {
    @EnvironmentObject private var model: AppModel

    @State private var email = ""
    @State private var password = ""
    @State private var serverURL = ""
    @State private var error: String?
    @State private var isBusy = false

    var body: some View {
        Form {
            Section("Account") {
                TextField("Email", text: $email)
                    .textContentType(.emailAddress)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                SecureField("Password", text: $password)
                    .textContentType(.password)
            }

            Section("Server") {
                TextField("Server URL", text: $serverURL)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            }

            if let error {
                Section {
                    Text(error).foregroundStyle(.red)
                }
            }

            Section {
                Button(action: logIn) {
                    if isBusy {
                        ProgressView()
                    } else {
                        Text("Log In")
                    }
                }
                .disabled(isBusy || email.isEmpty || password.isEmpty)
            }
        }
        .navigationTitle("Emmio")
        .onAppear { serverURL = model.baseURLString }
    }

    private func logIn() {
        error = nil
        isBusy = true
        if serverURL != model.baseURLString {
            model.updateBaseURL(serverURL)
        }
        Task {
            defer { isBusy = false }
            do {
                try await model.logIn(email: email, password: password)
            } catch {
                self.error = friendlyMessage(for: error)
            }
        }
    }
}

/// Turn an `EmmioError` into a short, user-facing line.
func friendlyMessage(for error: Error) -> String {
    if case let EmmioError.http(status, _) = error {
        switch status {
        case 401: return "Incorrect email or password."
        default: return "Server error (\(status))."
        }
    }
    return "Could not reach the server."
}
