// Client-side grading of typed answers.
//
// The server hands back the set of accepted forms for a `type_word` question;
// the client accepts an exact match against that set, matching the web client's
// auto-accept (`accepted.includes(input.value)`). Kept as a pure function so the
// acceptance rule has one tested home and can grow (e.g. trimming, folding)
// without touching the UI.

import Foundation

public enum Grading {
    /// Whether typed text counts as a correct answer to a `type_word` question.
    public static func accepts(_ typed: String, accepted: [String]) -> Bool {
        accepted.contains(typed)
    }
}
