# Emmio web interface

A minimal web client for the Emmio API: **semantic HTML + a little vanilla
JavaScript**, no framework, no build step, and (for now) no CSS — the markup is
plain so the design can be decided later.

It talks to the FastAPI JSON API (`emmio/api/app.py`) over `fetch`, holding the
access token in `localStorage`. The API serves these files itself (mounted at
`/app`), so the page and the API share an origin and there is no CORS to set up.

## Running

```sh
uvicorn emmio.api.app:app --reload
```

Then open <http://localhost:8000/app/>. (Set `EMMIO_JWT_SECRET` and
`DATABASE_URL` as needed; see the API module.)

## Files

| File            | Role                                                         |
|-----------------|--------------------------------------------------------------|
| `index.html`    | Home / dashboard: links to lexicons and courses.             |
| `login.html`    | Log in form.                                                 |
| `register.html` | Registration form.                                           |
| `lexicons.html` | Table of the user's lexicons (short info per lexicon).       |
| `lexicon.html`  | One lexicon: details and statistics (rate, precision, …).    |
| `check.html`    | Check a lexicon: shows a word, records know / don't know.    |
| `courses.html`  | Table of the user's learning courses.                        |
| `course.html`   | One course: details and statistics (due, learning, …).       |
| `learn.html`    | Repeat a course: shows a due word, records right / wrong.    |
| `app.js`        | Token storage, the `fetch` helper, and per-page logic.       |

`app.js` dispatches on `<body data-page="...">`, so each page is plain HTML that
just includes the one script. The lexicon-checking and learning pages share one
`runSession()` flow (next → reveal translation → answer), differing only in the
resource path (`/me/lexicons/{id}` vs `/me/courses/{id}`).

## Page flow

```mermaid
flowchart LR
    login["login.html<br/>log in"]
    register["register.html<br/>register"]
    home["index.html<br/>home / dashboard"]
    login <-->|"links"| register

    subgraph lex["Lexicons"]
        lexicons["lexicons.html<br/>list"]
        lexicon["lexicon.html<br/>details + stats"]
        check["check.html<br/>check words"]
        lexicons --> lexicon --> check
    end

    subgraph courses["Courses"]
        courseList["courses.html<br/>list"]
        course["course.html<br/>details + stats"]
        learn["learn.html<br/>repeat words"]
        courseList --> course --> learn
    end

    login -->|"log in → store token"| home
    home --> lexicons
    home --> courseList
    lexicons <-->|"nav"| courseList
```

## Authentication

The token is obtained once at login and attached to every later request:

- `POST /api/v1/auth/login` returns `{ access_token }`, stored under
  `localStorage["emmio_token"]`.
- The `api()` helper adds `Authorization: Bearer <token>` to each request.
- A `401` (missing or expired token) clears the token and returns to
  `login.html`.

## Request flow (a checking session)

The session page keeps a small client-side **queue** of upcoming words (each
with its translation already loading) and a **history** stack, so answering and
revealing a translation are instant, and any number of answers can be undone.

```mermaid
sequenceDiagram
    participant B as Browser (app.js)
    participant A as FastAPI (/api/v1)
    participant P as PostgreSQL

    B->>A: POST /auth/login (email, password)
    A-->>B: { access_token }  (stored in localStorage)

    Note over B: prefetch a queue of words
    B->>A: GET /me/lexicons/{id}/next?count=3
    A-->>B: { words: [...] }
    B->>A: GET /me/lexicons/{id}/translation?word=…  (per queued word)
    A-->>B: { dictionaries: [...] }

    loop per answer
        Note over B: show queued word instantly
        B->>A: POST /me/lexicons/{id}/answer (word, response)
        A-->>B: 204 No Content
        Note over B: push to history; pop next from queue
        B->>A: GET /next?count=1&exclude=<queued>  (top up, in background)
        A-->>B: { words: [...] }
    end

    opt undo (repeatable)
        B->>A: POST /me/lexicons/{id}/undo
        A->>P: delete latest record, rebuild word cache
        A-->>B: { word }  (re-presented to re-answer)
    end
```

`exclude` lists words already queued so a batch never repeats one. The same flow
drives learning, against `/me/courses/{id}` instead (its `/next` returns the
soonest-due questions). The `response` value depends on the resource:

- Lexicon `/answer`: a `LexiconResponse` — `know`, `dont`,
  `dont_but_proper_noun_too`, `not_a_word` (plus a "Know and skip" that sets the
  skip flag).
- Course `/answer`: a `Response` — `y` (right), `n` (wrong), `s` (skip).

## Scope and limitations

- **Learning is review-only.** The learning pages repeat words that are already
  being learned and are *due* (spaced repetition). Adding *new* words needs the
  interactive `Teacher` and is not exposed over the API yet, so a course with no
  due words shows "Nothing to repeat right now."
- **No create endpoints.** A freshly registered user has no lexicons or courses,
  and there is no API to create them yet — so the session pages are usable only
  by a user who already owns data in the database (e.g. a migrated CLI user).
- **Each `next` reloads server-side state.** A `/next` request reloads the
  lexicon/course from the database to pick words; the client buffer hides this
  latency, but a persistent server-side session would still be more efficient.
