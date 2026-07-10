// Turning the API's small HTML translation fragments into plain text.
//
// The API renders dictionary output as HTML (`<b>`, `<br>`, a handful of
// entities). The recognition card only needs readable text, so rather than pull
// in a full HTML renderer we strip tags and decode the few entities that
// actually appear. Kept here as a pure function so it is unit-tested directly.

import Foundation

public enum HTMLText {
    /// A minimal set of named entities the API's fragments use.
    private static let entities: [String: String] = [
        "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": "\"", "&#39;": "'",
        "&nbsp;": " ",
    ]

    /// Convert an HTML fragment to plain text: block tags become newlines, all
    /// other tags are dropped, named entities are decoded, and runs of blank
    /// lines and trailing spaces are collapsed.
    public static func plain(from html: String) -> String {
        // Give block-level breaks a newline so definitions stay on separate
        // lines once the tags are gone.
        var text = html
        for tag in ["<br>", "<br/>", "<br />", "</p>", "</div>", "</li>"] {
            text = text.replacingOccurrences(
                of: tag, with: "\n", options: .caseInsensitive
            )
        }

        // Drop every remaining tag.
        var stripped = ""
        var insideTag = false
        for character in text {
            switch character {
            case "<": insideTag = true
            case ">": insideTag = false
            default: if !insideTag { stripped.append(character) }
            }
        }

        for (entity, value) in entities {
            stripped = stripped.replacingOccurrences(of: entity, with: value)
        }

        // Trim each line and drop the blank ones the block breaks may leave.
        let lines = stripped
            .split(separator: "\n", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        return lines.joined(separator: "\n")
    }
}
