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

-- Languages.

-- One row per (user, language): the user's relationship with a language,
-- gathering everything they do in it — lexicons, learnings, and self-reported
-- proficiency estimates all point here. Unlike a course, this is not a
-- grouping the user invents: it exists once per language, keyed on the
-- language code, so there is exactly one place per language to attach to.
--
-- `main_lexicon_id` is the lexicon whose rate is taken as the user's level in
-- this language (added by an ALTER below, since `lexicons` is defined after
-- this table). One main per language is structural here — it is a single
-- column, rather than the flag plus partial unique index it replaced.
CREATE TABLE IF NOT EXISTS user_languages (
    id       SERIAL PRIMARY KEY,
    user_id  INT NOT NULL REFERENCES users(id),
    language TEXT NOT NULL,
    UNIQUE (user_id, language)
);

-- Courses and learning.

-- Stable identity for a course: a user-invented set that groups one or more
-- learnings (vocabulary, alphabet, irregular verbs, ...). `course_id` is
-- unique per user. A course has no configuration of its own beyond identity:
-- everything else lives on its learnings.
--
-- A course is the *non*-language grouping: unlike `user_languages`, it is
-- named by the user and need not relate to a language at all (Morse code,
-- say). A learning belongs to exactly one of the two — see `learnings`.
CREATE TABLE IF NOT EXISTS courses (
    id        SERIAL PRIMARY KEY,
    user_id   INT NOT NULL REFERENCES users(id),
    course_id TEXT NOT NULL,
    name      TEXT NOT NULL,
    language  TEXT NOT NULL,
    UNIQUE (user_id, course_id)
);

-- Stable identity for a learning (one drillable unit: vocabulary, an
-- alphabet, irregular verbs, ...), owned by a user. `learning_id` is unique
-- per user, so different users may both have an `fr` learning.
--
-- A learning hangs off exactly one parent: a `user_languages` row when it is
-- part of what the user does in a language, or a `courses` row when it
-- belongs to a user-invented grouping instead (Morse code has no language).
-- The CHECK below enforces exactly-one — never both, never neither — so
-- there is always a single answer to "what is this learning part of".
-- `course_id` was `NOT NULL` before `language_id` existed; the ALTERs below
-- relax it for existing databases.
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
    course_id         INT REFERENCES courses(id),
    language_id       INT REFERENCES user_languages(id),
    config            JSONB NOT NULL DEFAULT '{}',
    UNIQUE (user_id, learning_id),
    CONSTRAINT learnings_one_parent
        CHECK ((course_id IS NULL) <> (language_id IS NULL))
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
-- Which lexicon counts as the user's level in a language is *not* stored
-- here: it is `user_languages.main_lexicon_id`. This replaced an `is_main`
-- flag plus a partial unique index enforcing one main per language; the
-- patch section at the end of this file carries that flag over and drops it.
CREATE TABLE IF NOT EXISTS lexicons (
    id             SERIAL PRIMARY KEY,
    user_id        INT NOT NULL REFERENCES users(id),
    lexicon_id     TEXT NOT NULL,
    language       TEXT NOT NULL,
    language_id    INT REFERENCES user_languages(id),
    selection      TEXT,
    frequency_list JSONB,
    config         JSONB NOT NULL DEFAULT '{}',
    UNIQUE (user_id, lexicon_id)
);

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
    id          BIGSERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id),
    language    TEXT NOT NULL,
    language_id INT REFERENCES user_languages(id),
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

-- Language objects: patches and backfill.
--
-- Everything below patches an existing database forward to the
-- `user_languages` model above (the `CREATE TABLE`/column definitions there
-- only take effect on a fresh database). All of it is idempotent and safe to
-- re-run, including after `lexicons.is_main` has already been dropped.

-- A lexicon and a knowledge record each belong to one language object. The
-- denormalized `language` text columns are deliberately kept for now: every
-- existing query reads them, and they are backfilled from the same source,
-- so they cannot diverge without someone writing one and not the other.
ALTER TABLE lexicons
    ADD COLUMN IF NOT EXISTS language_id INT REFERENCES user_languages(id);
ALTER TABLE language_knowledge_records
    ADD COLUMN IF NOT EXISTS language_id INT REFERENCES user_languages(id);

-- A learning belongs to a course *or* a language (see `learnings` above).
ALTER TABLE learnings
    ADD COLUMN IF NOT EXISTS language_id INT REFERENCES user_languages(id);
ALTER TABLE learnings ALTER COLUMN course_id DROP NOT NULL;

-- The main lexicon becomes a column on the language object.
ALTER TABLE user_languages
    ADD COLUMN IF NOT EXISTS main_lexicon_id INT REFERENCES lexicons(id);

-- One language object per (user, language) the user has anything in. Courses
-- are included even though their learnings stay put: a user with a French
-- course should still find a French language object waiting when they move
-- those learnings over by hand.
INSERT INTO user_languages (user_id, language)
SELECT DISTINCT user_id, language FROM (
    SELECT user_id, language FROM lexicons
    UNION
    SELECT user_id, language FROM language_knowledge_records
    UNION
    SELECT user_id, language FROM courses
) AS every_language
ON CONFLICT (user_id, language) DO NOTHING;

UPDATE lexicons l SET language_id = ul.id
FROM user_languages ul
WHERE ul.user_id = l.user_id AND ul.language = l.language
  AND l.language_id IS DISTINCT FROM ul.id;

UPDATE language_knowledge_records k SET language_id = ul.id
FROM user_languages ul
WHERE ul.user_id = k.user_id AND ul.language = k.language
  AND k.language_id IS DISTINCT FROM ul.id;

-- Carries `lexicons.is_main` over to `user_languages.main_lexicon_id`, then
-- drops it so there is one source of truth. Guarded on the column still
-- existing, so re-running this script after the drop is a no-op rather than
-- an error.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'lexicons' AND column_name = 'is_main'
    ) THEN
        UPDATE user_languages ul SET main_lexicon_id = l.id
        FROM lexicons l
        WHERE l.user_id = ul.user_id AND l.language = ul.language
          AND l.is_main AND ul.main_lexicon_id IS NULL;
    END IF;
END $$;

DROP INDEX IF EXISTS lexicons_one_main_per_language;
ALTER TABLE lexicons DROP COLUMN IF EXISTS is_main;

-- The learnings CHECK cannot be added by `CREATE TABLE` on an existing
-- database; add it separately, once, and only when the data already
-- satisfies it.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'learnings_one_parent'
    ) THEN
        ALTER TABLE learnings ADD CONSTRAINT learnings_one_parent
            CHECK ((course_id IS NULL) <> (language_id IS NULL));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS lexicons_language ON lexicons (language_id);
CREATE INDEX IF NOT EXISTS learnings_language ON learnings (language_id);
CREATE INDEX IF NOT EXISTS language_knowledge_records_language
    ON language_knowledge_records (language_id);
