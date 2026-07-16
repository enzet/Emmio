<picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/enzet/Emmio/main/doc/header_white.svg">
    <img src="https://raw.githubusercontent.com/enzet/Emmio/main/doc/header_black.svg" alt="Emmio logo" height="80">
</picture>

**Emmio** is an experimental project focused on language learning. It provides
learning and testing algorithms:
  1. a [learning](#learning) system based on spaced repetition,
  2. a [lexicon](#lexicon) (vocabulary) level assessment tool.

The project manages four kinds of artifacts:
  - [dictionaries](#dictionary),
  - [sentence translations](#sentences),
  - [frequency and word lists](#frequency-and-word-lists),
  - [audio for words and sentences](#audio).

Emmio is primarily a terminal application, but it also includes an
experimental web interface and an iOS application built on top of a JSON API
(see [Other Interfaces](#other-interfaces)).

## Installation

Requires **Python 3.12** or later and a **PostgreSQL** server: learning and
lexicon records are stored in a PostgreSQL database (see `scripts/schema.sql`
for the table definitions). The connection string is taken from the
`EMMIO_DATABASE_URL` or `DATABASE_URL` environment variable and defaults to
`postgresql:///emmio`.

```shell
pip install git+https://github.com/enzet/emmio
```

Audio playback additionally requires the [mpv](https://mpv.io) player to be
installed on the system.

## Get Started

To run Emmio, simply execute

```shell
emmio
```

You can specify a data directory with the `--data` option and a username with
the `--user` option. If not specified, the data directory defaults to
`~/.emmio` and the username defaults to your current system username.

## Learning

```
> learn
```

The learning process is based on spaced repetition with increasing intervals.
Emmio picks new words from the word lists configured for the learning process
(optionally checking them against your lexicons and dictionaries first), shows
translations of the word with the word itself hidden, and asks you to type the
word in the learning language.

  - If the answer is correct, the word is scheduled for repetition: after the
    first correct answer it comes back in about 5 minutes, after the second in
    a day, and each subsequent correct answer doubles the interval.
  - If the answer is wrong, type `n` — the word and its translations are
    shown, and repetition starts over with short intervals.
  - Press <kbd>Enter</kbd> on empty input to see an example sentence with the
    word (press again for more sentences).
  - Type `p` to postpone the question, `/skip` to exclude the word from the
    learning process entirely, or `/stop` to finish the session.

Learning processes are configured in the user configuration file
(`users/<user name>/config.json`).

## Lexicon

```
> lexicon
```

The algorithm randomly presents words from the target language (weighted by
frequency). For each word, you need to indicate

  1. whether you know at least one meaning of this word (press <kbd>y</kbd> or
     <kbd>Enter</kbd>),
  2. whether you don’t know any meaning of the word (press <kbd>n</kbd>),
  3. whether the word is commonly used as a proper name or isn’t valid (press
     <kbd>-</kbd>).

Press <kbd>q</kbd> to finish.

After completion, the algorithm provides a non-negative number called _rate_,
that indicates your vocabulary level. A score of 0 means you don’t know any
words in the language, while infinity means you know every word in the
frequency list. This rate is most useful for tracking your learning progress
and comparing vocabulary levels between different users using the same
frequency list.

There is no upper limit for the rate, if you know meanings of all words in a
language, the rate is infinity. It’s finite though, if you don’t know meaning of
at least one word.

Column “Don’t understand” means how much you **don’t** understand of an
arbitrary text. Column “Understand” means how much you understand of an
arbitrary text.

| Rate | Don’t understand | Understand | Level * |
|-----:|-----------------:|-----------:|---------|
|   10 |           0.10 % |    99.90 % |         |
|    9 |           0.20 % |    99.80 % |         |
|    8 |           0.39 % |    99.61 % | C2      |
|    7 |           0.78 % |    99.22 % | C1      |
|    6 |           1.56 % |    98.44 % | B2      |
|    5 |           3.12 % |    96.88 % | B1      |
|    4 |           6.25 % |    93.75 % | A2      |
|    3 |          12.50 % |    87.50 % | A1      |
|    2 |          25.00 % |    75.00 % |         |
|    1 |          50.00 % |    50.00 % |         |
|    0 |         100.00 % |     0.00 % |         |

*&nbsp;Level is a **very rough** approximation of a level of the Common European
Framework of Reference for Languages. Please, don't take it as a strict
definition.

Lexicon checking is run with the `lexicon` command or `lexicon <language>`,
where `<language>` is a 2-letter ISO 639-1 language code. **Important**: a
lexicon needs a full (not stripped)
[frequency list](#frequency-and-word-lists).

### Visualizing the Checking Process

Two command-line tools compute how the rate estimate r̂ evolves as answers
accumulate and write the trajectories to CSV files; a third draws those CSV
files in a shared visual style.

To replay the recorded checking process of a real lexicon, run

```shell
python -m emmio.lexicon.replay --user $USER_ID --lexicon $LEXICON_ID
```

It reads the lexicon's answer log from the database, re-runs the production
rate estimator after every answer, and writes the estimate trajectory to a
CSV file (by default `${USER_ID}_${LEXICON_ID}.csv`, override with `--csv`).
The frequency list configured for the lexicon is loaded from the Emmio data
directory (`EMMIO_DATA_DIR`, default `~/.emmio`).

To compare how fast the checking methods converge on a synthetic language,
run

```shell
python -m emmio.lexicon.simulation --rate 3 --trials 5
```

It builds a fake Zipfian language, draws random knowledge profiles with a
chosen true rate, drives every checking method through the production
selection and estimation code, reports how fast each converges, and writes
the per-trial trajectories to a CSV file (by default `simulation.csv`,
override with `--csv`).

To visualize a CSV file written by either tool, run

```shell
python -m emmio.lexicon.visualize replay ${USER_ID}_${LEXICON_ID}.csv
python -m emmio.lexicon.visualize simulation simulation.csv
```

The replay plot shows the estimate trajectory with its ±1 standard deviation
band and ticks along the bottom marking the "don't know" answers; the
simulation plot shows per-trial and mean trajectories with the RMSE against
the realized rates. The output image file defaults to the CSV file with a
`.png` suffix, override with `--plot`.

## Data Directory Structure

Emmio data directory is located by default in `~/.emmio` and contains all
downloaded artifacts and their configuration files and collected user data.

  - `dictionaries` — single word translations.
  - `sentences` — whole sentence translations.
  - `lists` — frequency and word lists.
  - `audio` — audio files with word pronunciations.
  - `users` — user data.
    - `<user name>`
      - `config.json` — user configuration file.
      - `learn` — user learning process data.
      - `lexicon` — user lexicon checking data.

## Dictionary

Dictionaries are entities that provide definitions and translations for single
words. Artifacts are controlled by configuration file
`dictionaries/config.json`.

Emmio supports:
  - dictionaries stored in JSON files,
  - English Wiktionary (through [Kaikki.org](https://kaikki.org) website,
    containing dictionaries extracted from English Wiktionary using
    [wiktextract](https://github.com/tatuylonen/wiktextract)).

## Sentences

Sentences are example parts of texts in one language, translated into another
language. Artifacts are controlled by configuration file
`sentences/config.json`.

Emmio supports:
  - sentences and translations stored in simple text files (odd lines are
    sentences, even lines are translations),
  - sentences from [Tatoeba](https://tatoeba.org) project.

## Frequency and Word Lists

Frequency list is a relation between unique words and the number of their
occurrences in some text or a corpus of texts. Some frequency lists are
stripped (e.g. _6,500-lemma list based on the New Corpus for Ireland_). Lists
are controlled by configuration file `lists/config.json`.

Emmio supports:
  - word lists stored in text files,
  - [FrequencyWords](https://github.com/hermitdave/FrequencyWords)
    ([Hermit Dave](https://github.com/hermitdave)’s project, which contains full
    and stripped frequency lists extracted from subtitles in
    [Opensubtitles](https://www.opensubtitles.org) project).

### Wiktionary

Wiktionary project contains
[frequency lists](https://en.wiktionary.org/wiki/Wiktionary:Frequency_lists) for
different languages.

## Audio

Audio artifacts are word pronunciations, played during learning. Artifacts are
controlled by configuration file `audio/config.json`.

Emmio supports:
  - audio files stored in local directories,
  - pronunciations from
    [Wikimedia Commons](https://commons.wikimedia.org).

## Other Interfaces

Besides the terminal application, the repository contains experimental
clients built on top of a FastAPI backend:

  - **API** ([emmio/api/](emmio/api/)) — a JSON API with token-based
    authentication. Install its dependencies with `pip install -e .[api]` and
    run it with `uvicorn emmio.api.app:app --reload`.
  - **Web** ([web/](web/)) — a minimal JavaScript client served by the API at
    `http://localhost:8000/app/`; see [web/README.md](web/README.md).
  - **iOS** ([ios/](ios/)) — a SwiftUI application; see `ios/run.sh` for
    building and running it in the simulator.

## Contributing

Before contributing, please follow these steps:
  1. Install development dependencies with `pip install -e .[dev]`.
  2. Enable Git hooks with `git config core.hooksPath .githooks`.

### Before Committing

The pre-commit hook checks formatting and linting with
[Ruff](https://docs.astral.sh/ruff/), types with
[ty](https://github.com/astral-sh/ty), and runs the tests with pytest. To run
the same checks manually:

```shell
ruff format emmio/ tests/
ruff check emmio/ tests/
ty check emmio/ tests/
pytest
```

For commit messages we use 50/72 rule and each commit should start with a verb
in the present tense. We also use Markdown for commit message formatting.
