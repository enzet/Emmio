-- Emmio PostgreSQL schema.
--
-- A learning/lexicon is a stable identity per language; operational
-- configuration (frequency lists, dictionaries, sentence corpora) lives in
-- the `config` JSONB columns. The database is the single source of truth for
-- all user configuration; `config.json` files are only written by exports
-- for Git history, never read.

-- Users.

-- One row per user. `user_id` is the stable string login used by the CLI and
-- the API (e.g. `enzet`); `id` is the internal integer key referenced by owned
-- data. `email` and `hashed_password` are nullable: CLI-only and test users
-- need neither. `config` holds the user configuration sections that have no
-- dedicated tables (currently `listen`, plus historical sections such as
-- `read`), so that no configuration is read from `config.json` files.
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    email           TEXT UNIQUE,
    hashed_password TEXT,
    config          JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Courses and learning.

-- Stable identity for a course: a language-level set (e.g. "Armenian") that
-- groups one or more learnings (vocabulary, alphabet, irregular verbs, ...).
-- `course_id` is unique per user. A course has no configuration of its own
-- beyond identity: everything else lives on its learnings.
CREATE TABLE IF NOT EXISTS courses (
    id        SERIAL PRIMARY KEY,
    user_id   INT NOT NULL REFERENCES users(id),
    course_id TEXT NOT NULL,
    name      TEXT NOT NULL,
    language  TEXT NOT NULL,
    UNIQUE (user_id, course_id)
);

-- Stable identity for a learning (one drillable unit: vocabulary, an
-- alphabet, irregular verbs, ...), owned by a user and belonging to a course.
-- `learning_id` is unique per user, so different users may both have an `fr`
-- learning.
--
-- Unlike a lexicon, a learning has no statistical estimate that depends on
-- how questions are picked, so there is no immutable selection/frequency-list
-- tier: only `learning_language` is identity. Everything else (scheme,
-- dictionaries, sentences, audio, base languages, limits, ...) is mutable
-- preference and lives in `config`. Per-answer provenance is in
-- `learning_records.extra`.
CREATE TABLE IF NOT EXISTS learnings (
    id                SERIAL PRIMARY KEY,
    user_id           INT NOT NULL REFERENCES users(id),
    learning_id       TEXT NOT NULL,
    name              TEXT NOT NULL,
    learning_language TEXT NOT NULL,
    course_id         INT NOT NULL REFERENCES courses(id),
    config            JSONB NOT NULL DEFAULT '{}',
    UNIQUE (user_id, learning_id)
);

-- One row per user response. Self-describing: extra captures question
-- context, so records stay interpretable when learning configuration changes.
--
-- extra key dictionary (keys omitted when value is the default):
--   `t`  question type; absent = default (translation check)
--          `s`  type_in_sentence
--          `a`  audio_recognition
--          `q`  multiple_choice quiz
--   `si` sentence_id (integer); only when a sentence was used
--   `ai` audio_id (text); only for audio questions
--   `di` dictionary_id (text); only when non-default dictionary was used
--   `o`  options (text list); only for quiz questions
CREATE TABLE IF NOT EXISTS learning_records (
    id            BIGSERIAL PRIMARY KEY,
    learning_id   INT NOT NULL REFERENCES learnings(id),
    question_id   TEXT NOT NULL,
    response      CHAR(1) NOT NULL,
    -- `y` right, `n` wrong, `s` skip, `p` postpone.
    response_time TIMESTAMPTZ NOT NULL,
    request_time  TIMESTAMPTZ,
    extra         JSONB
);

CREATE TABLE IF NOT EXISTS learning_sessions (
    id          SERIAL PRIMARY KEY,
    learning_id INT NOT NULL REFERENCES learnings(id),
    type        TEXT NOT NULL,
    start       TIMESTAMPTZ NOT NULL,
    "end"       TIMESTAMPTZ,
    actions     INT
);

CREATE INDEX IF NOT EXISTS learning_records_learning_time
    ON learning_records (learning_id, response_time);
CREATE INDEX IF NOT EXISTS learning_records_learning_question
    ON learning_records (learning_id, question_id);
CREATE INDEX IF NOT EXISTS learning_sessions_learning_start
    ON learning_sessions (learning_id, start);

-- Lexicon.

-- Stable identity per lexicon, owned by a user. Several lexicons may exist per
-- language (e.g. `fr`, `fr_ex`, `fr_binary`). `lexicon_id` is unique per user.
--
-- Configuration is split by tier (see research/app.md "Lexicon configuration
-- model"):
--   - Identity (immutable; changing one means a different lexicon):
--       `language`, `selection`, and `frequency_list` (the sampling
--       distribution, only for sampling strategies; NULL otherwise).
--   - Mutable preferences (`config` JSONB; changing them does not alter the
--       meaning of past records): name, dictionaries, sentences, and pooled
--       `frequency_lists` for non-sampling strategies.
-- Per-answer provenance (which sentence/dictionary was shown) lives in
-- `lexicon_records.extra`, not here.
--
-- `is_main` marks the lexicon whose rate is taken as the user's level in that
-- language; the partial unique index allows at most one main per language.
CREATE TABLE IF NOT EXISTS lexicons (
    id             SERIAL PRIMARY KEY,
    user_id        INT NOT NULL REFERENCES users(id),
    lexicon_id     TEXT NOT NULL,
    language       TEXT NOT NULL,
    selection      TEXT,
    frequency_list JSONB,
    config         JSONB NOT NULL DEFAULT '{}',
    is_main        BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (user_id, lexicon_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS lexicons_one_main_per_language
    ON lexicons (user_id, language) WHERE is_main;

-- Each word stored once per lexicon. Also caches current word state
-- (`response`, `to_skip`, `last_seen`) for fast lookups without scanning
-- history; state columns are derived from lexicon_records and updated on
-- insert.
CREATE TABLE IF NOT EXISTS lexicon_words (
    id         SERIAL PRIMARY KEY,
    lexicon_id INT NOT NULL REFERENCES lexicons(id),
    word       TEXT NOT NULL,
    response   CHAR(1),
    to_skip    BOOLEAN,
    last_seen  TIMESTAMPTZ,
    UNIQUE (lexicon_id, word)
);

-- Full history: one row per response, user and auto alike.
--
-- response codes:
--   `K` `know`, `C` `know_semantic_class`, `D` `dont`, `N` `not_a_word`,
--   'B' `dont_but_proper_noun_too`, `?` `know_or_not_a_word`, `U` `unknown`.
--
-- extra key dictionary (keys omitted when value is the default):
--   `at` answer type; absent = user answer
--          `aa`  assume `not_a_word` by alphabet check
--          `ad`  assume `not_a_word` by dictionary check
--          `ps`  propagate skip
--          `pn`  propagate `not_a_word`
--          `pt`  propagate time
--   `rt` request_time; absent = same as `response_time` (auto answers)
--   `sk` to_skip flag (true or false); absent = not set
CREATE TABLE IF NOT EXISTS lexicon_records (
    id            BIGSERIAL PRIMARY KEY,
    word_id       INT NOT NULL REFERENCES lexicon_words(id),
    response      CHAR(1) NOT NULL,
    response_time TIMESTAMPTZ NOT NULL,
    extra         JSONB
);

CREATE TABLE IF NOT EXISTS lexicon_sessions (
    id         SERIAL PRIMARY KEY,
    lexicon_id INT NOT NULL REFERENCES lexicons(id),
    start      TIMESTAMPTZ NOT NULL,
    "end"      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS lexicon_records_word_time
    ON lexicon_records (word_id, response_time);
CREATE INDEX IF NOT EXISTS lexicon_words_lexicon_word
    ON lexicon_words (lexicon_id, word);
CREATE INDEX IF NOT EXISTS lexicon_sessions_lexicon_start
    ON lexicon_sessions (lexicon_id, start);

-- Frequency-list curation (SFWR curated panels).
--
-- A curated list is a fixed, pre-reviewed subsample of one specific
-- frequency list version, generalizing the "spine" from one word per stratum to
-- `n_c` per stratum.  Not owned by a user: curation is a property of the list,
-- open to any user, not per-learner.
--
-- Only human decisions are stored here. Automatic checks (alphabet,
-- dictionary, the cap_ratio proper-noun heuristic) stay live in
-- `LexiconChecker.do_skip` and are never cached in these tables.
CREATE TABLE IF NOT EXISTS curated_lists (
    id                SERIAL PRIMARY KEY,
    language          TEXT NOT NULL,
    frequency_list_id TEXT NOT NULL,
    name              TEXT NOT NULL,
    n_strata          INT NOT NULL DEFAULT 10,
    UNIQUE (language, frequency_list_id)
);

-- Each word stored once per curated list. Caches the consensus category
-- (mode of the word's `curated_word_records`, each curator's latest vote
-- counted once) for fast lookups without scanning history, mirroring
-- `lexicon_words`. `panel_order` is set once at insertion (from the
-- frequency-weighted draw order, or the fallback-promotion order) and never
-- re-sorted afterward — serving draws uniformly at random among a learner's
-- remaining unanswered words of a stratum, but the *order new words are
-- appended in* must stay stable for that random draw to remain valid.
--
-- category codes, in two groups (see `emmio.lexicon.core.NOT_TO_CHECK_TREE`):
--   group (1), words to check:   `W` real_word
--   group (2), words not to check, by why:
--     `P` proper_noun, `R` rare (rare/slang/retro word), `M` misspelling,
--     `S` misspelling_missing_spaces (words concatenated with no space
--     between them, e.g. from subtitle-extraction artifacts; a subcategory
--     of `M`), `D` misspelling_missing_diacritics (accents/diacritics
--     stripped, e.g. "uber" for "über"; another subcategory of `M`),
--     `G` misspelling_split_into_fragments (a single word wrongly split by a
--     stray space, e.g. "v isitar" for "visitar"; another subcategory of
--     `M`), `F` foreign_word, `N` not_a_word (generic/junk, no more specific
--     reason fits)
--   neither group: `U` unknown (no settled consensus yet)
CREATE TABLE IF NOT EXISTS curated_words (
    id              SERIAL PRIMARY KEY,
    curated_list_id INT NOT NULL REFERENCES curated_lists(id),
    word            TEXT NOT NULL,
    stratum         INT NOT NULL,
    panel_order     INT NOT NULL,
    category        CHAR(1) NOT NULL DEFAULT 'U',
    votes           INT NOT NULL DEFAULT 0,
    agreement       REAL,
    added_reason    TEXT NOT NULL,
    -- 'bootstrap' (initial per-stratum frequency-weighted draw) or
    -- 'fallback_promoted' (a learner hit it via raw-list fallback sampling).
    UNIQUE (curated_list_id, word)
);

-- Full history: every vote from every curator, kept (anyone may curate; the
-- consensus on `curated_words` is derived from this, never overwritten in
-- place — see "estimate curation error" in research/app.md).
CREATE TABLE IF NOT EXISTS curated_word_records (
    id              BIGSERIAL PRIMARY KEY,
    curated_word_id INT NOT NULL REFERENCES curated_words(id),
    category        CHAR(1) NOT NULL,
    curator_id      INT NOT NULL REFERENCES users(id),
    curated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS curated_words_list_stratum
    ON curated_words (curated_list_id, stratum, category);
CREATE INDEX IF NOT EXISTS curated_words_list_word
    ON curated_words (curated_list_id, word);
CREATE INDEX IF NOT EXISTS curated_word_records_word_time
    ON curated_word_records (curated_word_id, curated_at);

-- Self-reported language knowledge.

-- Full history: one row per self-reported proficiency estimate, kept and
-- never overwritten, so a user's assessment of a language over time stays
-- visible (unlike a lexicon's computed rate, this is entered by hand). Not
-- normalized into an identity/history pair like `curated_lists` — there is
-- no shared per-language cache to maintain, so one flat table is enough.
--
-- `kind` and `value` are validated against the curated taxonomy in
-- `emmio.language_knowledge` (`KNOWLEDGE_KINDS`), not a Postgres CHECK
-- constraint or enum, so the taxonomy can grow without a migration:
--   `native` (no value), `self`/`teacher` (CEFR-scaled), or a specific
--   certifying organization (e.g. `delf_dalf`, `ielts`, `hsk`), each with
--   its own value scale (CEFR letters, an organization-specific code, or a
--   bare number). `value` is NULL for kinds with no value scale (`native`);
--   a kind with `allows_other` (most of them) accepts free text there too,
--   alongside or instead of its curated values (see `is_valid_knowledge_
--   value`). `caption` is free text naming the kind more precisely, used
--   only by the generic `standardized_test` kind (`has_caption`); NULL
--   otherwise. `date` is NULL for a kind with `requires_date = False`
--   (`native`: a learner is not native "as of" some date) and required for
--   every other kind (see `is_valid_knowledge_date`).
CREATE TABLE IF NOT EXISTS language_knowledge_records (
    id         BIGSERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES users(id),
    language   TEXT NOT NULL,
    kind       TEXT NOT NULL,
    value      TEXT,
    caption    TEXT,
    date       DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Patches an existing table forward (the `CREATE TABLE` above only takes
-- effect on a fresh database); safe to re-run.
ALTER TABLE language_knowledge_records ADD COLUMN IF NOT EXISTS caption TEXT;
ALTER TABLE language_knowledge_records ALTER COLUMN date DROP NOT NULL;

CREATE INDEX IF NOT EXISTS language_knowledge_records_user_language
    ON language_knowledge_records (user_id, language, date);
