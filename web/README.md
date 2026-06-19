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

| File            | Role                                                        |
|-----------------|-------------------------------------------------------------|
| `index.html`    | Log in and register forms.                                  |
| `lexicons.html` | Lists the signed-in user's lexicons.                        |
| `check.html`    | Checks one lexicon: shows a word, records know / don't know.|
| `app.js`        | Token storage, the `fetch` helper, and per-page logic.      |

`app.js` dispatches on `<body data-page="...">`, so each page is plain HTML that
just includes the one script.

## Page flow

```mermaid
flowchart LR
    index["index.html<br/>log in / register"]
    lexicons["lexicons.html<br/>list lexicons"]
    check["check.html<br/>check a word"]

    index -->|"log in → store token"| lexicons
    lexicons -->|"pick a lexicon"| check
    check -->|"← back"| lexicons
    lexicons -->|"log out → clear token"| index
```

## Authentication

The token is obtained once at login and attached to every later request:

- `POST /api/v1/auth/login` returns `{ access_token }`, stored under
  `localStorage["emmio_token"]`.
- The `api()` helper adds `Authorization: Bearer <token>` to each request.
- A `401` (missing or expired token) clears the token and returns to
  `index.html`.

## Request flow (a checking session)

```mermaid
sequenceDiagram
    participant B as Browser (app.js)
    participant A as FastAPI (/api/v1)
    participant P as PostgreSQL

    B->>A: POST /auth/login (email, password)
    A->>P: verify credentials
    A-->>B: { access_token }
    Note over B: store token in localStorage

    B->>A: GET /me/lexicons  (Bearer token)
    A->>P: list the user's lexicons
    A-->>B: [ { lexicon_id, language }, ... ]

    loop until no words left
        B->>A: GET /me/lexicons/{id}/next
        A->>P: answered words + frequency list
        A-->>B: { word }
        B->>A: POST /me/lexicons/{id}/answer (word, response)
        A->>P: record the answer
        A-->>B: 204 No Content
    end
```

The `response` sent to `/answer` is a `LexiconResponse` value: `know`, `dont`,
`dont_but_proper_noun_too`, or `not_a_word`.

## Scope and limitations

The interface only covers what the API exposes today: **authentication and
lexicon checking**.

- **Learning** (the spaced-repetition flow) is not on the API yet, so it is not
  in the web interface.
- A **freshly registered** user has no lexicons, and there is **no
  create-lexicon endpoint** yet — so the checking page is only usable by a user
  who already owns lexicons in the database. Creating lexicons over the API is a
  pending backend task.
