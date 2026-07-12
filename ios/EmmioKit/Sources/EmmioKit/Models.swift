// Codable mirrors of the Emmio API's JSON payloads.
//
// The API serialises with snake_case keys (`course_id`, `access_token`); the
// client decodes with `.convertFromSnakeCase`, so the Swift properties stay
// camelCase and need no explicit `CodingKeys`. Only the fields the recognition
// learning loop uses are modelled — the API returns more.

import Foundation

/// An issued access token, from `POST /api/v1/auth/login`.
public struct Token: Codable, Sendable {
    public let accessToken: String
    public let tokenType: String
}

/// A learning course list row, from `GET /api/v1/me/courses`.
///
/// `Hashable` so it can drive SwiftUI value-based navigation.
public struct CourseSummary: Codable, Hashable, Identifiable, Sendable {
    /// Distinct words studied.
    public let words: Int
    /// Total answers recorded.
    public let answers: Int
    public let courseId: String
    public let name: String
    public let learningLanguage: String

    public var id: String { courseId }
}

/// One upcoming word with its last-answer context, an element of `NextWords`.
public struct WordCard: Codable, Identifiable, Sendable {
    public let word: String
    /// Human label of the last answer, e.g. `"right"`, or `nil` if never asked.
    public let lastResponse: String?
    /// When the word was last answered (ISO-8601 string), or `nil`.
    public let lastTime: String?
    /// Typed answers that count as correct; unused by the recognition loop.
    public let accepted: [String]?

    public var id: String { word }
}

/// A batch of upcoming words, soonest-due first; empty when the queue is spent.
///
/// From `GET /api/v1/me/courses/{course_id}/next`.
public struct NextWords: Codable, Sendable {
    /// ISO code of the words' language, e.g. `fr`.
    public let language: String
    public let words: [WordCard]
}

/// One language offered by `/lexicon-languages` (languages a course or
/// lexicon can be created for) or `/translation-languages` (targets words can
/// be translated into).
public struct LanguageOption: Codable, Sendable {
    /// ISO code, e.g. `fr`.
    public let language: String
}

/// The identifier assigned to a freshly created course, from
/// `POST /me/courses`.
public struct CreatedCourse: Codable, Sendable {
    public let courseId: String
}

/// One dictionary's rendering of a word, as an HTML fragment.
public struct DictionaryTranslation: Codable, Sendable {
    /// Dictionary name.
    public let dictionary: String
    /// Definitions/translations as an HTML fragment (see `HTMLText.plain`).
    public let html: String
}

/// A word's translation, split per dictionary, from `.../translation`.
public struct Translation: Codable, Sendable {
    public let word: String
    public let dictionaries: [DictionaryTranslation]
}

/// An example sentence for a word, from `.../sentence`.
///
/// A recall prompt: the word is blanked out and the sentence comes with one of
/// its translations into a base language. `sentence` is `nil` when no
/// translated example exists for the word.
public struct Sentence: Codable, Sendable {
    public let word: String
    /// The sentence as a safe HTML fragment, the word blanked, or `nil`.
    public let sentence: String?
    /// A translation of the sentence, or `nil`.
    public let translation: String?
    /// The example's id, recorded with the answer as provenance.
    public let sentenceId: Int?
}

/// A user's answer to a repetition question: the `Response` codes the API
/// stores (`y` right, `n` wrong, `s` skip). See `emmio/learn/core.py`.
public enum LearnResponse: String, Sendable {
    case right = "y"
    case wrong = "n"
    case skip = "s"
}

/// How a review question was asked, stored as provenance with the answer and
/// deciding how the client renders and grades it. Values match the
/// `QUESTION_TYPE_*` codes in `emmio/api/app.py`.
public enum QuestionType: String, Sendable {
    /// See the word, self-assess, reveal the meaning.
    case know
    /// Pick the translation among several.
    case choice
    /// Match several words to their translations.
    case connect
    /// See the meaning, type the word.
    case typeWord = "type_word"
}

/// One word and its short translation, for a `connect` (matching) question.
public struct ConnectPair: Codable, Hashable, Sendable {
    public let word: String
    public let translation: String

    public init(word: String, translation: String) {
        self.word = word
        self.translation = translation
    }
}

/// A review question of one of several types, from `.../question`.
///
/// Only the fields a given `type` needs are set; `type` is `nil` when nothing is
/// due. The client renders by `type`, grades the answer against the provided
/// key (`accepted`/`answer`/`pairs`), and records each covered word via
/// `.../answer`.
public struct Question: Codable, Sendable {
    /// The question kind as a raw string; `nil` when nothing is due. Read
    /// `kind` for the typed form.
    public let type: String?
    /// ISO code of the words' language.
    public let language: String
    /// The word(s) the question covers (used when recording answers).
    public let words: [String]
    /// `type_word`: the typed answers that count as correct.
    public let accepted: [String]?
    /// `choice`: the translations to pick from.
    public let options: [String]?
    /// `choice`: the correct option.
    public let answer: String?
    /// `connect`: the words and their translations to match.
    public let pairs: [ConnectPair]?

    public init(
        type: String?,
        language: String,
        words: [String] = [],
        accepted: [String]? = nil,
        options: [String]? = nil,
        answer: String? = nil,
        pairs: [ConnectPair]? = nil
    ) {
        self.type = type
        self.language = language
        self.words = words
        self.accepted = accepted
        self.options = options
        self.answer = answer
        self.pairs = pairs
    }

    /// The typed question kind, or `nil` when nothing is due (or unrecognised).
    public var kind: QuestionType? {
        type.flatMap(QuestionType.init(rawValue:))
    }

    /// Build a local `type_word` question for a single word — used to
    /// re-present a word after an undo, mirroring the web client.
    public static func typeWord(word: String, language: String) -> Question {
        Question(
            type: QuestionType.typeWord.rawValue,
            language: language,
            words: [word],
            accepted: [word]
        )
    }
}

/// The word an undo freed up (or `nil`), from `.../undo`.
public struct NextWord: Codable, Sendable {
    public let word: String?
}

/// The next new word to add to a course, from `.../new`.
///
/// `word` is `nil` when none remains: the daily limit is reached, the course's
/// question lists are exhausted, or the server gave up early on a long run of
/// dictionary checks.
public struct NewQuestion: Codable, Sendable {
    public let word: String?
    /// Typed answers that count as correct.
    public let accepted: [String]?
    /// Lexicon to ask know/don't-know in *before* learning this word, or `nil`
    /// to learn it directly. The client posts the answer to that lexicon:
    /// "know" skips the word, "don't know" admits it to learning.
    public let checkLexicon: String?
    /// New words still allowed today (the course's `max_for_day`).
    public let remainingToday: Int
}

/// A user's answer to a lexicon know/don't-know check: the `LexiconResponse`
/// values the API accepts. See `emmio/lexicon/core.py`.
public enum LexiconAnswer: String, Sendable {
    case know
    case dont
}
