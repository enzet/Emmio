<picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/enzet/Emmio/master/doc/header_white.svg">
    <img src="https://raw.githubusercontent.com/enzet/Emmio/master/doc/header_black.svg" alt="Emmio logo" height="80">
</picture>

__Emmio__ is an experimental project on languages and learning. It consists of:

  * _Learning_:
    [Leitner's algorithm](https://en.wikipedia.org/wiki/Leitner_system) based
    flashcard learning system.
  * _Lexicon_: check and track vocabulary level.

## Installation

Requires __Python 3.10__.

```shell
pip install git+https://github.com/enzet/emmio
```

## Server

```shell
emmio server
```

To run Emmio server on the Telegram, use

```shell
emmio server --mode telegram --token ${TELEGRAM_TOKEN}
```

## Lexicon

```shell
emmio lexicon
```

The algorithm will randomly (based on frequency) offer you words of the target
language. For each word you have to decide 

  1. either you know at least one meaning of this word (press <kbd>y</kbd> or 
     <kbd>Enter</kbd>),
  2. or you don't know any meaning of this word (press <kbd>n</kbd>), 
  3. or the word is often used as a proper name or doesn't exist at all (press
     <kbd>-</kbd>).

To finish press <kbd>q</kbd>.
 
After that algorithm will provide you a non-negative number called _rate_, that
somehow describes your vocabulary. 0 means you know not a single word of the
language and infinity means you know absolutely all words in the frequency list.
The better use of the rate is to track your language learning progress and to
compare vocabulary of different people using one frequency list.

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

There is [Hermit Dave](https://github.com/hermitdave)'s project
[FrequencyWords](https://github.com/hermitdave/FrequencyWords), which contains
full and stripped frequency lists extracted from subtitles in
[Opensubtitles](https://www.opensubtitles.org) project.

