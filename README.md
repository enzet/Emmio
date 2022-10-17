<img align="right" src="https://raw.githubusercontent.com/enzet/Emmio/master/doc/logo_blue.svg" />

__Emmio__ is an experimental project on languages and learning. It consists of:

  * _Learning_:
    [Leitner's algorithm](https://en.wikipedia.org/wiki/Leitner_system) based
    flashcard learning system.
  * _Lexicon_: check and track vocabulary level.

## Installation ##

Requires __Python 3.9__.

```shell
pip install git+https://github.com/enzet/emmio
```

## Run ##

```shell
emmio ${DATA_DIRECTORY} ${USER_NAME}
```

## Lexicon ##

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
  * `frequency list id` is an idenrifier of [full frequency file](#frequency). 
    __Important__: for Lexicon you can use only full (not stripped) frequency 
    list.

## Frequency ##

There are full and stripped frequency lists. Stripped list uses only top part of
the full list. Some algorithms require full lists.

There are a lot of projects with frequency lists.

### FrequencyWords (Opensubtitles) ###

There is [Hermit Dave](https://github.com/hermitdave)'s project
[FrequencyWords](https://github.com/hermitdave/FrequencyWords), which contains
full and stripped frequency lists base on
[Opensubtitles](https://www.opensubtitles.org) project. You can get frequency
list using this command:

```shell script
wget https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/${LANGUAGE_CODE}/${LANGUAGE_CODE}_full.txt \
    --output-document=${LANGUAGE_CODE}_opensubtitles_2018.txt
```

### Wiktionary ###

Wiktionary project contains
[frequency lists](https://en.wiktionary.org/wiki/Wiktionary:Frequency_lists) for
different languages.
