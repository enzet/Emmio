import XCTest

@testable import EmmioKit

/// A `HTTPFetching` mock: records the requests it receives and replays a queue
/// of canned `(status, body)` responses in order.
final class MockHTTP: HTTPFetching, @unchecked Sendable {
    struct Stub {
        let status: Int
        let body: Data

        static func ok(_ json: String) -> Stub {
            Stub(status: 200, body: Data(json.utf8))
        }
        static func noContent() -> Stub { Stub(status: 204, body: Data()) }
        static func status(_ code: Int, _ body: String = "") -> Stub {
            Stub(status: code, body: Data(body.utf8))
        }
    }

    private let lock = NSLock()
    private(set) var requests: [URLRequest] = []
    private var stubs: [Stub]

    init(_ stubs: [Stub]) { self.stubs = stubs }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        lock.lock()
        defer { lock.unlock() }
        requests.append(request)
        let stub = stubs.isEmpty ? Stub(status: 200, body: Data()) : stubs.removeFirst()
        let response = HTTPURLResponse(
            url: request.url!, statusCode: stub.status,
            httpVersion: nil, headerFields: nil
        )!
        return (stub.body, response)
    }
}

final class EmmioKitTests: XCTestCase {
    private let baseURL = URL(string: "http://localhost:8000")!

    // MARK: - Decoding

    func testCourseSummaryDecodesSnakeCase() throws {
        let json = """
        [{"course_id":"fr","name":"French","learning_language":"fr",
          "words":42,"answers":100}]
        """
        let courses = try JSONDecoder.snakeCase().decode(
            [CourseSummary].self, from: Data(json.utf8)
        )
        XCTAssertEqual(courses.count, 1)
        XCTAssertEqual(courses[0].courseId, "fr")
        XCTAssertEqual(courses[0].learningLanguage, "fr")
        XCTAssertEqual(courses[0].words, 42)
        XCTAssertEqual(courses[0].id, "fr")
    }

    func testNextWordsDecodes() throws {
        let json = """
        {"language":"fr","words":[
          {"word":"bonjour","last_response":"right",
           "last_time":"2026-07-01T12:00:00Z","accepted":["bonjour"]},
          {"word":"chat","last_response":null,"last_time":null,"accepted":null}]}
        """
        let next = try JSONDecoder.snakeCase().decode(
            NextWords.self, from: Data(json.utf8)
        )
        XCTAssertEqual(next.language, "fr")
        XCTAssertEqual(next.words.map(\.word), ["bonjour", "chat"])
        XCTAssertEqual(next.words[0].lastResponse, "right")
        XCTAssertNil(next.words[1].lastResponse)
    }

    func testQuestionDecodesChoice() throws {
        let json = """
        {"type":"choice","language":"fr","words":["chat"],
         "options":["cat","dog","tree","house"],"answer":"cat",
         "accepted":null,"pairs":null}
        """
        let question = try JSONDecoder.snakeCase().decode(
            Question.self, from: Data(json.utf8)
        )
        XCTAssertEqual(question.kind, .choice)
        XCTAssertEqual(question.words, ["chat"])
        XCTAssertEqual(question.answer, "cat")
        XCTAssertEqual(question.options?.count, 4)
    }

    func testQuestionDecodesConnectPairs() throws {
        let json = """
        {"type":"connect","language":"fr","words":["chat","chien"],
         "pairs":[{"word":"chat","translation":"cat"},
                  {"word":"chien","translation":"dog"}]}
        """
        let question = try JSONDecoder.snakeCase().decode(
            Question.self, from: Data(json.utf8)
        )
        XCTAssertEqual(question.kind, .connect)
        XCTAssertEqual(
            question.pairs,
            [
                ConnectPair(word: "chat", translation: "cat"),
                ConnectPair(word: "chien", translation: "dog"),
            ]
        )
    }

    func testQuestionNilTypeWhenNothingDue() throws {
        let json = #"{"type":null,"language":"fr","words":[]}"#
        let question = try JSONDecoder.snakeCase().decode(
            Question.self, from: Data(json.utf8)
        )
        XCTAssertNil(question.type)
        XCTAssertNil(question.kind)
    }

    func testTypeWordFactoryBuildsLocalQuestion() {
        let question = Question.typeWord(word: "chat", language: "fr")
        XCTAssertEqual(question.kind, .typeWord)
        XCTAssertEqual(question.words, ["chat"])
        XCTAssertEqual(question.accepted, ["chat"])
    }

    // MARK: - Grading

    func testGradingAcceptsExactMatchOnly() {
        XCTAssertTrue(Grading.accepts("chat", accepted: ["chat", "chatte"]))
        XCTAssertFalse(Grading.accepts("Chat", accepted: ["chat"]))
        XCTAssertFalse(Grading.accepts("cha", accepted: ["chat"]))
    }

    // MARK: - HTML

    func testHTMLPlainStripsTagsAndDecodesEntities() {
        let html = "<b>chat</b>: cat &amp; kitten<br><i>animal</i>"
        XCTAssertEqual(HTMLText.plain(from: html), "chat: cat & kitten\nanimal")
    }

    func testHTMLPlainCollapsesBlankLines() {
        let html = "<p>one</p><p></p><p>two</p>"
        XCTAssertEqual(HTMLText.plain(from: html), "one\ntwo")
    }

    // MARK: - Requests

    func testLoginPostsFormEncodedBodyAndStoresToken() async throws {
        let mock = MockHTTP([.ok(#"{"access_token":"tok123","token_type":"bearer"}"#)])
        let client = EmmioClient(baseURL: baseURL, session: mock)

        let token = try await client.logIn(email: "a@b.com", password: "p&w")
        XCTAssertEqual(token.accessToken, "tok123")
        let authenticated = await client.isAuthenticated
        XCTAssertTrue(authenticated)

        let request = mock.requests[0]
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/api/v1/auth/login")
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "Content-Type"),
            "application/x-www-form-urlencoded"
        )
        let body = String(decoding: request.httpBody ?? Data(), as: UTF8.self)
        XCTAssertTrue(body.contains("username=a%40b.com"), body)
        XCTAssertTrue(body.contains("password=p%26w"), body)
        XCTAssertTrue(body.contains("remember=true"), body)
        // Login must not send a stale Authorization header.
        XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
    }

    func testAuthenticatedRequestsCarryBearerToken() async throws {
        let mock = MockHTTP([.ok("[]")])
        let client = EmmioClient(baseURL: baseURL, session: mock, token: "tok")
        _ = try await client.courses()
        XCTAssertEqual(
            mock.requests[0].value(forHTTPHeaderField: "Authorization"),
            "Bearer tok"
        )
    }

    func testNextBuildsCountAndExcludeQuery() async throws {
        let mock = MockHTTP([.ok(#"{"language":"fr","words":[]}"#)])
        let client = EmmioClient(baseURL: baseURL, session: mock, token: "tok")
        _ = try await client.next(courseId: "fr", count: 5, exclude: ["a", "b"])

        let components = URLComponents(
            url: mock.requests[0].url!, resolvingAgainstBaseURL: false
        )!
        let items = components.queryItems ?? []
        XCTAssertEqual(components.path, "/api/v1/me/courses/fr/next")
        XCTAssertTrue(items.contains(URLQueryItem(name: "count", value: "5")))
        XCTAssertEqual(
            items.filter { $0.name == "exclude" }.map(\.value), ["a", "b"]
        )
    }

    func testAnswerPostsQuestionTypeAsJSON() async throws {
        let mock = MockHTTP([.noContent()])
        let client = EmmioClient(baseURL: baseURL, session: mock, token: "tok")
        try await client.answer(
            courseId: "fr", word: "chat", response: .wrong,
            questionType: .typeWord, seconds: 2.5
        )

        let request = mock.requests[0]
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/api/v1/me/courses/fr/answer")
        let body = try XCTUnwrap(request.httpBody)
        let json = try JSONSerialization.jsonObject(with: body) as! [String: Any]
        XCTAssertEqual(json["word"] as? String, "chat")
        XCTAssertEqual(json["response"] as? String, "n")
        XCTAssertEqual(json["question_type"] as? String, "type_word")
        XCTAssertEqual(json["seconds"] as? Double, 2.5)
    }

    func testAnswerDefaultsToKnowQuestionType() async throws {
        let mock = MockHTTP([.noContent()])
        let client = EmmioClient(baseURL: baseURL, session: mock, token: "tok")
        try await client.answer(courseId: "fr", word: "chat", response: .right)
        let json = try JSONSerialization.jsonObject(
            with: XCTUnwrap(mock.requests[0].httpBody)
        ) as! [String: Any]
        XCTAssertEqual(json["question_type"] as? String, "know")
    }

    func testUndoPostsAndReturnsWord() async throws {
        let mock = MockHTTP([.ok(#"{"word":"chat"}"#)])
        let client = EmmioClient(baseURL: baseURL, session: mock, token: "tok")
        let word = try await client.undo(courseId: "fr")
        XCTAssertEqual(word, "chat")
        XCTAssertEqual(mock.requests[0].httpMethod, "POST")
        XCTAssertEqual(mock.requests[0].url?.path, "/api/v1/me/courses/fr/undo")
    }

    func testNon2xxSurfacesAsHTTPError() async throws {
        let mock = MockHTTP([.status(401, "Invalid or expired token.")])
        let client = EmmioClient(baseURL: baseURL, session: mock, token: "tok")
        do {
            _ = try await client.courses()
            XCTFail("expected an error")
        } catch let EmmioError.http(status, body) {
            XCTAssertEqual(status, 401)
            XCTAssertEqual(body, "Invalid or expired token.")
        }
    }
}

private extension JSONDecoder {
    static func snakeCase() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}
