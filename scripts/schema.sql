-- Emmio PostgreSQL schema.
--
-- A course/lexicon is a stable identity per language; operational configuration
-- (frequency lists, dictionaries, sentence corpora) stays in the user
-- configuration file.

-- Learning.

-- Stable identity for a learning course. Base languages are a display
-- preference and live in user settings, not here.
CREATE TABLE IF NOT EXISTS learn_courses (
    id                SERIAL PRIMARY KEY,
    course_id         TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    learning_language TEXT NOT NULL
);

-- One row per user response. Self-describing: extra captures question
-- context, so records stay interpretable when course configuration changes.
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
CREATE TABLE IF NOT EXISTS learn_records (
    id            BIGSERIAL PRIMARY KEY,
    course_id     INT NOT NULL REFERENCES learn_courses(id),
    question_id   TEXT NOT NULL,
    response      CHAR(1) NOT NULL,
    -- `y` right, `n` wrong, `s` skip, `p` postpone.
    response_time TIMESTAMPTZ NOT NULL,
    request_time  TIMESTAMPTZ,
    extra         JSONB
);

CREATE TABLE IF NOT EXISTS learn_sessions (
    id        SERIAL PRIMARY KEY,
    course_id INT NOT NULL REFERENCES learn_courses(id),
    type      TEXT NOT NULL,
    start     TIMESTAMPTZ NOT NULL,
    "end"     TIMESTAMPTZ,
    actions   INT
);

CREATE INDEX IF NOT EXISTS learn_records_course_time
    ON learn_records (course_id, response_time);
CREATE INDEX IF NOT EXISTS learn_records_course_question
    ON learn_records (course_id, question_id);
CREATE INDEX IF NOT EXISTS learn_sessions_course_start
    ON learn_sessions (course_id, start);

-- Lexicon.

-- Stable identity per lexicon. Several lexicons may exist per language
-- (e.g. `fr`, `fr_ex`, `fr_binary`).
CREATE TABLE IF NOT EXISTS lexicons (
    id         SERIAL PRIMARY KEY,
    lexicon_id TEXT NOT NULL UNIQUE,
    language   TEXT NOT NULL
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
--   `K` `know`, `D` `dont`, `N` `not_a_word`, 'B' `dont_but_proper_noun_too`,
--   `?` `know_or_not_a_word`, `U` `unknown`.
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
