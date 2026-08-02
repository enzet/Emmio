# Emmio web interface

A minimal web client for the Emmio API: **semantic HTML + a little vanilla
JavaScript**, no framework, no build step, and (for now) no CSS — the markup is
plain so the design can be decided later.

It talks to the FastAPI JSON API (`emmio/api/app.py`) over `fetch`, holding the
access token in `localStorage`. The API serves these files itself (mounted at
`/app`), so the page and the API share an origin and there is no CORS to set up.

## Running

```shell
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
| `learn.html`    | Learn a course: type the word (due repetitions and new ones).|
| `curated-lists.html` | Table of curated lists, with a total/remaining-for-you word count. |
| `curate.html`   | Curate a list: shows a word, records its category.           |
| `app.js`        | Entry point: dispatches on `<body data-page="...">`.         |

`app.js` is loaded as an ES module (`<script type="module">`) and only holds
the dispatch table; the actual logic lives under `js/`, one module per concern:

| Module                  | Role                                                            |
|--------------------------|------------------------------------------------------------------|
| `js/api.js`              | Token storage, the `fetch` helper, `requireAuth`.                |
| `js/format.js`           | Formatting/DOM helpers shared by every page (rate, dates, `<select>` fill, …). |
| `js/charts.js`           | The inline-SVG charts: rate trajectory, language history, strata wheel. |
| `js/forms.js`            | Shared "create a lexicon / course / learning" form wiring.       |
| `js/check-session.js`    | `runSession()` (lexicon checking) and the check page.             |
| `js/learn-session.js`    | `runLearnSession()` (course learning) and the learn page.         |
| `js/curate-session.js`   | The curated-lists picker and the curate page (`emmio curate`'s web equivalent). |
| `js/auth-pages.js`       | Landing, login, register.                                        |
| `js/home-pages.js`       | Dashboard and the per-language page.                              |
| `js/lexicon-pages.js`    | Lexicon list, lexicon detail + settings, add-a-lexicon.           |
| `js/course-pages.js`     | Course list, course detail + learning settings, add-a-course/learning. |
| `js/profile.js`          | Profile page.                                                    |

Lexicon checking uses `runSession()` (a yes/no flow: next → reveal translation
→ answer). Learning uses `runLearnSession()`, which renders whichever review
question type the server's `/question` endpoint chose:

- **type the word** — meaning (word blanked) + a translated example shown; type
  the word, auto-accepted on match against the server's `accepted`.
- **know** — see the word, self-assess Know / Don't-know, then the meaning shows.
- **choice** — pick the translation among options.
- **connect** — match several words to their translations at once.

New words still come from `/new` (taught as type-the-word, after the optional
`ask_lexicon` check). Each answered word is recorded via `/answer` with its
question type.

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

    subgraph curation["Curation"]
        curatedLists["curated-lists.html<br/>list"]
        curate["curate.html<br/>curate words"]
        curatedLists --> curate
    end

    login -->|"log in → store token"| home
    home --> lexicons
    home --> courseList
    home --> curatedLists
    lexicons <-->|"nav"| courseList
    lexicons <-->|"nav"| curatedLists
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

`exclude` lists words already queued so a batch never repeats one. Learning runs
the analogous flow against `/me/courses/{id}` (its `/next` returns the
soonest-due questions); when those run out it pulls new words from `/new`, which
may first ask a know/don't-know check recorded in the course's `ask_lexicon`
before the word is taught. The `response` value depends on the resource:

> **Lexicon `/next` records as it samples.** It draws frequency-weighted words
> and, for every word it does *not* present (already known, flagged "skip",
> "not a word", foreign-alphabet, or answered recently), writes an automatic
> record — `propagate_skip`, `propagate_time`, `propagate_not_a_word`, or
> `assume_not_a_word` — instead of excluding it. This keeps the record stream a
> faithful frequency-weighted sample, which is what the vocabulary rate is
> computed from. A high-rate lexicon therefore writes many such records per
> request and may return fewer than `count` words (the client just tops up).


- Lexicon `/answer`: a `LexiconResponse` — `know`, `know_semantic_class`,
  `dont`, or `not_a_word` (plus a "Know and skip" that sets the skip flag).
  `dont_but_proper_noun_too` is legacy-only, no longer sent by the check
  page. A `not_a_word` answer may carry an extra `category` field — one of
  `NOT_TO_CHECK_CATEGORY_CODES` (`emmio/lexicon/core.py`), e.g. `P` for a
  proper noun — reporting *why*; the server writes that straight into the
  shared curated panel (`curated_words`/`curated_word_records`) as a real
  curation vote, the same one `emmio curate` would record, rather than a
  separate mechanism (see `_record_not_to_check_vote`).
- Course `/answer`: a `Response` — `y` (right), `n` (wrong), `s` (skip).

## Curation

`curate.html`/`curate-session.js` is the web equivalent of `emmio curate`: instead of a
know/don't-know question, the curator picks which category a word belongs to (`GET
/curation/categories` lists them, so the client never hardcodes the taxonomy). Simpler
than a checking session — no prefetch queue, since `GET /curation/{id}/next` is a cheap
query (not an expensive selector draw worth amortizing), and no undo (a curation vote is
real history from the moment it lands):

```mermaid
sequenceDiagram
    participant B as Browser (curate-session.js)
    participant A as FastAPI (/api/v1)

    B->>A: GET /curation/lists
    A-->>B: [{ curated_list_id, name, words, unvoted }, ...]
    Note over B: curated-lists.html links to curate.html?id=<id>

    B->>A: GET /curation/categories
    A-->>B: [{ code, label }, ...]  (used to build the answer buttons)

    loop per word
        B->>A: GET /curation/{id}/next
        A-->>B: { word, stratum, auto_resolved }  (word is null when done)
        B->>A: GET /curation/{id}/translation?word=…
        A-->>B: { dictionaries: [...] }
        B->>A: GET /curation/{id}/sentence?word=…
        A-->>B: { sentence }
        B->>A: POST /curation/{id}/answer (word, category)
        A-->>B: 204 No Content
    end
```

`/next` skips words an automatic check already resolves (outside the alphabet, `cap_ratio`
past the proper-noun threshold, or clear dictionary evidence either way) without writing
anything — `auto_resolved` in the response is purely informational (e.g. for a "skipped N
words" status line), not something the client acts on. See
`emmio.lexicon.curation.classify_automatically`, shared with the CLI's `emmio curate`.

## Scope and limitations

- **Learning teaches new words too.** The learning page repeats *due* words and,
  when none remain, adds new ones drawn from the course's frequency lists
  (`/new`), honoring its `check_lexicons` / `ask_lexicon`. Typing is graded
  against the card's `accepted` forms (today the exact word). Audio
  pronunciation is the one `Teacher` feature not yet exposed.
- **Create from the home page.** A freshly registered user has no lexicons or
  courses; the home page offers "Add a lexicon" (`POST /me/lexicons`) and "Add a
  course" (`POST /me/courses`) to make the first ones. Both draw on the shared
  frequency lists, dictionaries and Tatoeba sentences for the chosen language.
- **Each `next` reloads server-side state.** A `/next` request reloads the
  lexicon/course from the database to pick words; the client buffer hides this
  latency, but a persistent server-side session would still be more efficient.
