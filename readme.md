<img align="right" src="https://raw.githubusercontent.com/enzet/Emmio/master/doc/logo.png" />

Emmio is a tool box for learning. It contains:

  * _Teacher_:
    [Leitner's algorithm](https://en.wikipedia.org/wiki/Leitner_system) based
    flashcard learning system.
  * _Lexicon_: vocabulary test.
  * _Text_ analysis.

[![Build Status](https://travis-ci.org/enzet/Emmio.svg?branch=master)](https://travis-ci.org/enzet/Emmio)

## Requirements ##

  * Python 3,
  * PyYAML (at least 4.2b1).

## Installation ##

```shell script
pip install -r requirements.txt
```

## Teacher ##

Is a flashcard learning system based on Leitner's algorithm.

```shell script
python3 emmio.py teacher ${OPTIONS}
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

```shell script
python3 emmio.py lexicon \
    --language  ${LANGUAGE_CODE} \
    --lexicon   ${LEXICON_JSON_FILE_NAME} \
    --frequency ${FULL_FREQUENCY_FILE_NAME}    
```

Arguments:

  * `${LANGUAGE_CODE}` is 2-letters ISO 639-1 language code (e.g. `en` for
    English and `ru` for Russian).
  * `${LEXICON_JSON_FILE_NAME}` is a name of file with lexicon (e.g.
    `lexicon_john_de.json`). If file doesn't exist, it will be created.
  * `${FREQUENCY_FILE_NAME}` is a name of [full frequency file](#frequency). 
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

## Text analysis ##

Create frequency list from the text.

```shell script
python3 emmio.py text \
    --language ${LANGUAGE_CODE} \
    --input    ${INPUT_TEXT_FILE_NAME} \
    --output   ${OUTPUT_JSON_FREQUENCY_FILE_NAME}
```

## Examples ##

### Check vocabulary ###

Check German vocabulary test based on Opensubtitles frequency list:

```shell script
wget https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/de/de_full.txt \
    --output-document=de_opensubtitles_2018.txt
python3 emmio.py lexicon --language de --lexicon lexicon_de.json \
    --frequency de_opensubtitles_2018.txt --skip-known --skip-unknown
```
