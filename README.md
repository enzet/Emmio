<picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/enzet/Emmio/master/doc/header_white.svg">
    <img src="https://raw.githubusercontent.com/enzet/Emmio/master/doc/header_black.svg" alt="Emmio logo" height="80">
</picture>

__Emmio__ is an experimental project focused on language learning. It provides
learning and testing algorithms:
  1. a [learning](#learning) system based on spaced repetition,
  2. a [lexicon](#lexicon) (vocabulary) level assessment tool.

The project manages four kinds of artifacts:
  - [dictionaries](#dictionary),
  - [sentence translations](#sentences),
  - [frequency and word lists](#frequency-and-word-lists),
  - [audio for words and sentences](#audio).

## Installation

Requires __Python 3.12__ or later.

```shell
pip install git+https://github.com/enzet/emmio
```

## Get Started

To run Emmio, simply execute

```shell
emmio
```

You can specify a data directory with the `--data` option and a username with
the `--user` option. If not specified, the data directory defaults to
`~/.emmio` and the username defaults to your current system username.

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

| Rate | Don’t understand | Understand | Level |
|-----:|-----------------:|-----------:|-------|
|   10 |           0.10 % |    99.90 % |       |
|    9 |           0.20 % |    99.80 % |       |
|    8 |           0.39 % |    99.61 % | C2    |
|    7 |           0.78 % |    99.22 % | C1    |
|    6 |           1.56 % |    98.44 % | B2    |
|    5 |           3.12 % |    96.88 % | B1    |
|    4 |           6.25 % |    93.75 % | A2    |
|    3 |          12.50 % |    87.50 % | A1    |
|    2 |          25.00 % |    75.00 % |       |
|    1 |          50.00 % |    50.00 % |       |
|    0 |         100.00 % |     0.00 % |       |


In order to run lexicon checking, simply execute `lexicon` command or `lexicon <language>` command, where `<language>` is 2-letters ISO 639-1 language code.

  * `frequency list id` is an identifier of [full frequency file](#frequency). 
    __Important__: for Lexicon you can use only full (not stripped) frequency 
    list.

## Data directory structure

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
words.  Artifacts are controlled by configuration file
`dictionaries/config.json`.

Emmio supports:
  - dictionaries stored in JSON files,
  - English Wiktionary (through
    [WiktionaryParser](https://github.com/Suyash458/WiktionaryParser)).

## Sentences

## Frequency and word lists

Frequency list is a relation between unique words and the number of their
occurrences in some text or a corpus of texts.  Some frequency lists are
stripped (e.g. _6,500-lemma list based on the New Corpus for Ireland_). Lists
are controlled by configuration file `lists/config.json`.

Emmio supports:
  - word lists stored in text files,
  - FrequencyWords from Opensubtitles.

### FrequencyWords (Opensubtitles)

There is [Hermit Dave](https://github.com/hermitdave)’s project
[FrequencyWords](https://github.com/hermitdave/FrequencyWords), which contains
full and stripped frequency lists extracted from subtitles in
[Opensubtitles](https://www.opensubtitles.org) project.

### Wiktionary

Wiktionary project contains
[frequency lists](https://en.wiktionary.org/wiki/Wiktionary:Frequency_lists) for
different languages.

## Audio

## Server

Emmio can be used as a server.

```shell
emmio server
```

To run Emmio server on the Telegram, use

```shell
emmio server --mode telegram --token ${TELEGRAM_TOKEN}
```
