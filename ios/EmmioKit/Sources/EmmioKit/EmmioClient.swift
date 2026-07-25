// The Emmio API client used by the iOS app.
//
// A thin async wrapper over the routes in `emmio/api/app.py`, holding just the
// calls the learning loop needs: log in, list courses and learnings, pull the
// next due words, draw new words to add (with their lexicon pre-check),
// reveal a word's translation, example sentence and pronunciation, and record
// an answer. It is an `actor` so the bearer token is mutated safely from
// concurrent callers, and it takes its transport through the `HTTPFetching`
// protocol so tests can drive it with canned responses instead of the
// network.

import Foundation

/// The transport `EmmioClient` sends requests over. `URLSession` conforms, so
/// production code passes `.shared`; tests pass a mock that returns fixtures.
public protocol HTTPFetching: Sendable {
    func data(for request: URLRequest) async throws -> (Data, URLResponse)
}

extension URLSession: HTTPFetching {}

/// A failure talking to the API.
public enum EmmioError: Error, Sendable, Equatable {
    /// A non-2xx response, with the status code and the body for context.
    case http(status: Int, body: String)
    /// The response was not an `HTTPURLResponse` (should not happen in practice).
    case invalidResponse
}

public actor EmmioClient {
    /// Base URL of the API, e.g. `http://localhost:8000` (no trailing `/api`).
    public let baseURL: URL
    private let session: HTTPFetching
    private var token: String?

    private let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    /// - Parameters:
    ///   - baseURL: the API origin, without a path.
    ///   - session: the transport; defaults to `URLSession.shared`.
    ///   - token: a previously stored access token to start authenticated.
    public init(
        baseURL: URL,
        session: HTTPFetching = URLSession.shared,
        token: String? = nil
    ) {
        self.baseURL = baseURL
        self.session = session
        self.token = token
    }

    /// Whether a token is set (so the caller can route to the login screen).
    public var isAuthenticated: Bool { token != nil }

    /// Adopt (or clear, with `nil`) the bearer token, e.g. after restoring one
    /// from storage or logging out.
    public func setToken(_ token: String?) {
        self.token = token
    }

    // MARK: - Endpoints

    /// Log in with email and password, storing and returning the access token.
    ///
    /// The login route is OAuth2 password-form, so the body is form-encoded with
    /// the email as `username`. With `remember` the token lasts 7 days instead
    /// of an hour.
    @discardableResult
    public func logIn(
        email: String, password: String, remember: Bool = true
    ) async throws -> Token {
        var request = URLRequest(url: url("/api/v1/auth/login"))
        request.httpMethod = "POST"
        request.setValue(
            "application/x-www-form-urlencoded",
            forHTTPHeaderField: "Content-Type"
        )
        request.httpBody = Self.formEncode([
            "username": email,
            "password": password,
            "remember": remember ? "true" : "false",
        ])
        let token = try await send(request, as: Token.self, authorized: false)
        self.token = token.accessToken
        return token
    }

    /// List the authenticated user's courses (language-level sets).
    public func courses() async throws -> [CourseSummary] {
        try await send(
            request(for: "/api/v1/me/courses"), as: [CourseSummary].self
        )
    }

    /// Get a course's identity plus its learnings.
    public func courseDetail(courseId: String) async throws -> CourseDetail {
        let path = "/api/v1/me/courses/\(escape(courseId))"
        return try await send(request(for: path), as: CourseDetail.self)
    }

    /// List languages a new course (or lexicon) can be created for — those
    /// with a frequency list to draw words from and Tatoeba sentences for
    /// examples. ISO codes, sorted.
    public func lexiconLanguages() async throws -> [String] {
        try await send(
            request(for: "/api/v1/lexicon-languages"), as: [LanguageOption].self
        ).map(\.language)
    }

    /// List languages words and sentences can be translated into. ISO codes.
    public func translationLanguages() async throws -> [String] {
        try await send(
            request(for: "/api/v1/translation-languages"),
            as: [LanguageOption].self
        ).map(\.language)
    }

    /// Create an empty course (a language-level set), returning its id.
    ///
    /// The id is the language code, suffixed when one already exists. A
    /// learning must be added to it afterward via `createLearning`.
    public func createCourse(
        language: String, name: String
    ) async throws -> String {
        let body: [String: Any] = ["language": language, "name": name]
        var request = self.request(for: "/api/v1/me/courses")
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await send(request, as: CreatedCourse.self).courseId
    }

    /// Delete a course. Succeeds only while it has no learnings left — the
    /// server responds 409 otherwise.
    public func deleteCourse(courseId: String) async throws {
        var request = self.request(for: "/api/v1/me/courses/\(escape(courseId))")
        request.httpMethod = "DELETE"
        try await sendNoContent(request)
    }

    /// Add a learning to an existing course, in the course's language,
    /// returning its id.
    ///
    /// The server assembles the configuration (frequency list, dictionaries,
    /// sentences, audio) from its shared data; the id is the course's
    /// language code, suffixed when one already exists.
    public func createLearning(
        courseId: String, translationLanguages: [String]
    ) async throws -> String {
        let body: [String: Any] = [
            "translation_languages": translationLanguages,
        ]
        let path = "/api/v1/me/courses/\(escape(courseId))/learnings"
        var request = self.request(for: path)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await send(request, as: CreatedLearning.self).learningId
    }

    /// Delete a learning and all its answer history. Irreversible.
    public func deleteLearning(learningId: String) async throws {
        var request = self.request(
            for: "/api/v1/me/learnings/\(escape(learningId))"
        )
        request.httpMethod = "DELETE"
        try await sendNoContent(request)
    }

    /// Pull the next words due for repetition in a learning, soonest-due
    /// first.
    ///
    /// - Parameters:
    ///   - count: how many words to prefetch into the session queue.
    ///   - exclude: words already queued on the client, to avoid duplicates.
    public func next(
        learningId: String, count: Int = 10, exclude: [String] = []
    ) async throws -> NextWords {
        var items = [URLQueryItem(name: "count", value: String(count))]
        items += exclude.map { URLQueryItem(name: "exclude", value: $0) }
        let path = "/api/v1/me/learnings/\(escape(learningId))/next"
        return try await send(request(for: path, query: items), as: NextWords.self)
    }

    /// Get the next due review question, of a type the server chooses.
    ///
    /// `type` on the result is `nil` when nothing is due. `exclude` lists words
    /// to skip (already presented this pass).
    public func question(
        learningId: String, exclude: [String] = []
    ) async throws -> Question {
        let items = exclude.map { URLQueryItem(name: "exclude", value: $0) }
        let path = "/api/v1/me/learnings/\(escape(learningId))/question"
        return try await send(request(for: path, query: items), as: Question.self)
    }

    /// Get the next new word to add to the learning, from its question lists.
    ///
    /// `word` on the result is `nil` when none remains. `exclude` lists words
    /// already decided this session (answered or admitted), which the stateless
    /// server would otherwise return again.
    public func newWord(
        learningId: String, exclude: [String] = []
    ) async throws -> NewQuestion {
        let items = exclude.map { URLQueryItem(name: "exclude", value: $0) }
        let path = "/api/v1/me/learnings/\(escape(learningId))/new"
        return try await send(
            request(for: path, query: items), as: NewQuestion.self
        )
    }

    /// Record a know/don't-know answer for a word in a lexicon — the new-word
    /// pre-check named by `NewQuestion.checkLexicon`.
    public func answerLexicon(
        lexiconId: String, word: String, response: LexiconAnswer
    ) async throws {
        let body: [String: Any] = [
            "word": word,
            "response": response.rawValue,
        ]
        let path = "/api/v1/me/lexicons/\(escape(lexiconId))/answer"
        var request = self.request(for: path)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        try await sendNoContent(request)
    }

    /// Undo the most recent answer, returning the word freed up (or `nil`).
    public func undo(learningId: String) async throws -> String? {
        var request = self.request(
            for: "/api/v1/me/learnings/\(escape(learningId))/undo"
        )
        request.httpMethod = "POST"
        return try await send(request, as: NextWord.self).word
    }

    /// Reveal a word's translation (the meaning shown after self-assessing).
    ///
    /// `hideWord` is `false` here so the full meaning is shown, matching the
    /// recognition card's "reveal the answer" step.
    public func translation(
        learningId: String, word: String, hideWord: Bool = false
    ) async throws -> Translation {
        let items = [
            URLQueryItem(name: "word", value: word),
            URLQueryItem(name: "hide_word", value: hideWord ? "true" : "false"),
        ]
        let path = "/api/v1/me/learnings/\(escape(learningId))/translation"
        return try await send(
            request(for: path, query: items), as: Translation.self
        )
    }

    /// Get one example sentence for a word (blanked, with a translation).
    ///
    /// `sentence` on the result is `nil` when no translated example exists. A
    /// slow lookup: fetch it after the card is presented, not before.
    public func sentence(
        learningId: String, word: String
    ) async throws -> Sentence {
        let items = [URLQueryItem(name: "word", value: word)]
        let path = "/api/v1/me/learnings/\(escape(learningId))/sentence"
        return try await send(request(for: path, query: items), as: Sentence.self)
    }

    /// Fetch a pronunciation recording for a word, or `nil` when there is
    /// none — no recording found, no audio configured, or playback disabled
    /// for the learning (all reported by the server as 404).
    public func audio(learningId: String, word: String) async throws -> Data? {
        let items = [URLQueryItem(name: "word", value: word)]
        let path = "/api/v1/me/learnings/\(escape(learningId))/audio"
        do {
            return try await perform(request(for: path, query: items))
        } catch EmmioError.http(404, _) {
            return nil
        }
    }

    /// Record an answer to a review question.
    ///
    /// - Parameters:
    ///   - response: right / wrong / skip.
    ///   - questionType: how the word was asked, stored as provenance (`qt`).
    ///   - sentenceId: the example sentence shown, stored as provenance.
    ///   - sessionId: the open learning session, so the answer counts into
    ///     its log row; the answer is recorded either way.
    ///   - seconds: how long the card was on screen, stored as provenance.
    public func answer(
        learningId: String,
        word: String,
        response: LearnResponse,
        questionType: QuestionType = .know,
        sentenceId: Int? = nil,
        sessionId: String? = nil,
        seconds: Double? = nil
    ) async throws {
        var body: [String: Any] = [
            "word": word,
            "response": response.rawValue,
            "question_type": questionType.rawValue,
        ]
        if let sentenceId { body["sentence_id"] = sentenceId }
        if let sessionId { body["session_id"] = sessionId }
        if let seconds { body["seconds"] = seconds }

        var request = self.request(
            for: "/api/v1/me/learnings/\(escape(learningId))/answer"
        )
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        try await sendNoContent(request)
    }

    /// Open a learning session: answers carrying the returned identifier are
    /// grouped into one session log row when it closes. Also warms the
    /// server's cached learning, making the first question fast.
    public func openLearningSession(
        learningId: String, type: String = "repeat_and_learn_new"
    ) async throws -> String {
        let path = "/api/v1/me/learnings/\(escape(learningId))/sessions"
        var request = self.request(for: path)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(
            withJSONObject: ["type": type]
        )
        return try await send(request, as: OpenedSession.self).sessionId
    }

    /// Close a learning session, writing its log row. Idempotent: closing an
    /// unknown or already-closed session is a safe no-op, and a session that
    /// is never closed is finalized by the server when it expires.
    public func closeLearningSession(
        learningId: String, sessionId: String
    ) async throws {
        let path = "/api/v1/me/learnings/\(escape(learningId))/sessions/"
            + "\(escape(sessionId))/close"
        var request = self.request(for: path)
        request.httpMethod = "POST"
        try await sendNoContent(request)
    }

    // MARK: - Request plumbing

    private func url(_ path: String, query: [URLQueryItem] = []) -> URL {
        var components = URLComponents(
            url: baseURL.appendingPathComponent(path),
            resolvingAgainstBaseURL: false
        )!
        if !query.isEmpty { components.queryItems = query }
        return components.url!
    }

    /// A GET request to `path` carrying the bearer token.
    private func request(
        for path: String, query: [URLQueryItem] = []
    ) -> URLRequest {
        var request = URLRequest(url: url(path, query: query))
        if let token {
            request.setValue(
                "Bearer \(token)", forHTTPHeaderField: "Authorization"
            )
        }
        return request
    }

    /// Send a request and decode its JSON body.
    ///
    /// `authorized` re-applies the bearer token to a request built elsewhere
    /// (login builds its own, unauthenticated, so passes `false`).
    private func send<T: Decodable>(
        _ request: URLRequest, as type: T.Type, authorized: Bool = true
    ) async throws -> T {
        var request = request
        if authorized, let token {
            request.setValue(
                "Bearer \(token)", forHTTPHeaderField: "Authorization"
            )
        }
        let data = try await perform(request)
        return try decoder.decode(T.self, from: data)
    }

    /// Send a request that returns no body (a 204), applying the bearer token.
    private func sendNoContent(_ request: URLRequest) async throws {
        _ = try await perform(request)
    }

    /// Run a request and surface non-2xx responses as `EmmioError.http`.
    private func perform(_ request: URLRequest) async throws -> Data {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw EmmioError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            throw EmmioError.http(
                status: http.statusCode,
                body: String(decoding: data, as: UTF8.self)
            )
        }
        return data
    }

    private func escape(_ component: String) -> String {
        component.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed
        ) ?? component
    }

    /// Form-encode a body for the login route.
    static func formEncode(_ fields: [String: String]) -> Data {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._~")
        let pairs = fields.map { key, value in
            let k = key.addingPercentEncoding(withAllowedCharacters: allowed) ?? key
            let v = value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
            return "\(k)=\(v)"
        }
        return Data(pairs.joined(separator: "&").utf8)
    }
}
