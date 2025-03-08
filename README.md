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
  2. wheter you don’t know any meaning of this word (press <kbd>n</kbd>),
  3. or the word is often used as a proper name or doesn’t exist at all (press
     <kbd>-</kbd>).

Press <kbd>q</kbd> to finish.
 
After completion, the algorithm provides a non-negative number called _rate_,
that indicates your vocabulary level. A score of 0 means you don't know any
words in the language, while infinity means you know every word in the
frequency list. This rate is most useful for tracking your learning progress
and comparing vocabulary levels between different users using the same
frequency list.

There is no upper limit for the rate, if you know meanings of all words in a
language, the rate is infinity. It’s finite though, if you don’t know meaning of
at least one word.

| Rate        | Level                            |
|-------------|----------------------------------|
| near 3      | Beginner, elementary             |
| near 5      | Intermediate, upper intermediate |
| near 7      | Advanced, proficient             |
| more than 9 | Native                           |

Lexicon configuration:

```
"lexicon": {
    "<language>": "<frequency list id>",
    ...
}
```

  * `language` is 2-letters ISO 639-1 language code (e.g. `en` for
    English and `ru` for Russian).
  * `frequency list id` is an identifier of [full frequency file](#frequency). 
    __Important__: for Lexicon you can use only full (not stripped) frequency 
    list.

### Wiktionary

Wiktionary project contains
[frequency lists](https://en.wiktionary.org/wiki/Wiktionary:Frequency_lists) for
different languages.

## Data directory structure

Emmio data directory is located by default in `~/.emmio` and contains all
downloaded artifacts and their configuration files and collected user data.

  - `dictionaries` — single word translations.
  - `sentences` — whole sentence translations.
  - `lists` — frequency lists and simple word lists.
  - `users` — user data.
    - `<user name>`
      - `config.json` — user configuration file.
      - `learn` — user learning process data.
      - `lexicon` — user lexicon checking data.

### Dictionaries

Dictionaries are entities that provide definitions and translations for single
words.  Artifacts are controlled by configuration file
`dictionaries/config.json`.

Emmio supports:
  - dictionaries stored in JSON files,
  - English Wiktionary (through
    [WiktionaryParser](https://github.com/Suyash458/WiktionaryParser)).

### Frequency lists and word lists

Frequency list is a relation between unique words and the number of their
occurrences in some text of a corpus of texts.  Some frequency lists are
stripped (e.g. 6,500-lemma list based on the New Corpus for Ireland).

#### FrequencyWords (Opensubtitles)

There is [Hermit Dave](https://github.com/hermitdave)’s project
[FrequencyWords](https://github.com/hermitdave/FrequencyWords), which contains
full and stripped frequency lists extracted from subtitles in
[Opensubtitles](https://www.opensubtitles.org) project.
