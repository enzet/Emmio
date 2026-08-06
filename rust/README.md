# freqlist

Unicode-aware frequency list generator.

Output format is `word count cap_ratio` per line, most frequent first
(`cap_ratio` is `NA` if the word never occurs outside a sentence start). If
`--language` names a language where capitalization doesn't signal a proper
noun (e.g. German — see Language support below), the `cap_ratio` field is
dropped entirely instead: `NA` on every single line would just be confusing
noise, not data. The first two fields always match the
[FrequencyWords](https://github.com/hermitdave/FrequencyWords) project's
format, so it remains a drop-in source for Emmio's `FrequencyWordsList`
either way.

## Build

```shell
cargo build --release
```

## Download a corpus

OPUS distributes OpenSubtitles as monolingual, untokenised, gzipped text (one
sentence per line). Pick a language code and version:

```shell
# v2024 is the newest; v2018 matches the existing FrequencyWords lists.
curl -O https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2024/mono/fr.txt.gz
```

Browse languages at <https://opus.nlpl.eu/OpenSubtitles/corpus/version/OpenSubtitles>.

## Generate a list

```shell
# `.gz` is decompressed on the fly; plain text also works.
./target/release/freqlist --input fr.txt.gz --output fr_full.txt
```

Options:

- `--min-count N` — drop words seen fewer than `N` times.
- `--keep-numbers` — keep tokens containing digits (dropped by default).
- `--keep-case` — disable Unicode lowercasing.
- `--stats PATH` — also write a capitalization / proper-noun report (see below).
- `--output-cap PATH` — also write a copy of the output restricted to words
  with `cap_ratio >= 0.2` (same `word count cap_ratio` format; words with an
  undefined `cap_ratio`, `NA`, are excluded — as is every word, for a
  language where the field is dropped from the main output too). A quick
  way to review proper-noun/honorific-noun candidates without the bulk of
  the full list.
- `--proper-noun-threshold R` — off-start title-case fraction to flag a proper
  noun (default `0.8`; empirically the best F1 tradeoff against dictionary
  ground truth on a real OpenSubtitles English sample — `0.5` lets through
  ~46% false positives, mostly honorific address terms).
- `--proper-noun-min-count N` — minimum off-start occurrences before flagging
  (default `5`).
- `--language CODE` — ISO code (e.g. `tr`, `de`, `en`, `hy`) enabling
  language-specific casing and proper-noun rules (see Language support).
- `--type {plain|subtitles}` — corpus type (default `plain`). `subtitles` drops
  whole lines that are bracketed annotations like `[door creaks]` (sound
  descriptions, not speech); a line with only a leading speaker tag
  (`[John] Hello`) is kept.
- `--stop-at N` — stop after counting `N` words. Checked after each line, so
  the last line processed is never cut off mid-sentence.

## Capitalization and proper-noun detection

With `--stats PATH`, the tool writes a TSV:

```
word    total   titlecased   sentence_initial   cap_ratio   is_proper_noun
```

`cap_ratio` is the fraction of a word's *non-sentence-initial* occurrences that
are title-cased. Sentence-initial occurrences are excluded because every word is
capitalized at the start of a sentence, so that position carries no information.
A word that stays capitalized mid-sentence (`Paris`, `France`, `Tom`) scores high
and is flagged; a word capitalized only at sentence start (`je`, `the`) scores
near zero and is not.

Sentence starts are detected as the first word of a line (OPUS dumps are one
sentence per line) plus any word following `.`, `!`, `?`, or `…`.

Caveats: honorifically capitalized common nouns (`Dieu`, `Président`,
`Seigneur`) can be flagged — raise `--proper-noun-threshold` to suppress them;
multi-word names (`New York`) are flagged as separate tokens; and in English the
pronoun `I` is always capitalized mid-sentence, so it will be flagged.

## Language support

`freqlist` has no built-in language list: it tokenises with Unicode word
segmentation (UAX #29) and case-folds with Unicode rules, so quality depends on
the **script**, not the language. This table rates every language in the OPUS
OpenSubtitles corpus (v2018, 62 languages).

**Frequency list** column — quality of the `word count` output:

- 🟢 **good** — space-separated script, tokens are real words.
- 🟡 **caveats** — usable but with a script- or language-specific issue.
- 🔴 **broken** — no spaces between words; UAX #29 yields characters or
  syllables, not words. Needs a dictionary-based segmenter.

**Proper nouns** column — quality of the capitalization heuristic:

- 🟢 **works** — bicameral (cased) script: Latin, Cyrillic, Greek, Armenian.
- ⚪ **inert** — script has no letter case, so nothing is flagged. Harmless.
- 🟠 **unreliable** — script is cased but a language rule defeats the heuristic.
- ⛔ **n/a** — tokenisation is broken, so the question doesn't arise.

### Tier 1 — full support (cased, space-separated)

Frequency and proper-noun detection both work. Adding any of these is just
"download the OPUS file and run."

| Code | Language | Script | Freq | PN | Difficulties / notes |
|---|---|---|---|---|---|
| af | Afrikaans | Latin | 🟢 | 🟢 | Compounds inflate unique forms (a lemma issue, not tokenisation). |
| bg | Bulgarian | Cyrillic | 🟢 | 🟢 | — |
| br | Breton | Latin | 🟢 | 🟢 | `c'h` trigraph kept as one token (apostrophe-internal). |
| bs | Bosnian | Latin | 🟢 | 🟢 | — |
| ca | Catalan | Latin | 🟢 | 🟢 | Interpunct `l·l` (`col·legi`) may split; clitic apostrophes (`l'home`). |
| cs | Czech | Latin | 🟢 | 🟢 | — |
| da | Danish | Latin | 🟢 | 🟢 | Compounds. |
| el | Greek | Greek | 🟢 | 🟢 | Bicameral; final-sigma ς vs σ are distinct forms. |
| en | English | Latin | 🟢 | 🟢 | Pass `--language en` to suppress the pronoun **I** false positive. |
| eo | Esperanto | Latin | 🟢 | 🟢 | — |
| es | Spanish | Latin | 🟢 | 🟢 | `¿¡` handled as punctuation. |
| et | Estonian | Latin | 🟢 | 🟢 | Agglutinative → many surface forms. |
| eu | Basque | Latin | 🟢 | 🟢 | Agglutinative. |
| fr | French | Latin | 🟢 | 🟢 | Clitics like `c'est` kept joined (differs from FrequencyWords). |
| gl | Galician | Latin | 🟢 | 🟢 | — |
| hr | Croatian | Latin | 🟢 | 🟢 | — |
| hu | Hungarian | Latin | 🟢 | 🟢 | Agglutinative. |
| hy | Armenian | Armenian | 🟢 | 🟢 | Bicameral; Armenian full stop `։` and question `՞` are recognised as sentence ends. |
| id | Indonesian | Latin | 🟢 | 🟢 | Reduplication (`anak-anak`). |
| is | Icelandic | Latin | 🟢 | 🟢 | — |
| it | Italian | Latin | 🟢 | 🟢 | Clitic apostrophes (`l'acqua`). |
| kk | Kazakh | Cyrillic | 🟢 | 🟢 | — |
| lt | Lithuanian | Latin | 🟢 | 🟢 | — |
| lv | Latvian | Latin | 🟢 | 🟢 | — |
| mk | Macedonian | Cyrillic | 🟢 | 🟢 | — |
| ms | Malay | Latin | 🟢 | 🟢 | Reduplication. |
| nl | Dutch | Latin | 🟢 | 🟢 | `IJ`/`ij` digraph; compounds. |
| no | Norwegian | Latin | 🟢 | 🟢 | Compounds. |
| pl | Polish | Latin | 🟢 | 🟢 | — |
| pt | Portuguese | Latin | 🟢 | 🟢 | Enclitic hyphens (`dá-me`) split into pieces. |
| pt_br | Portuguese (BR) | Latin | 🟢 | 🟢 | As `pt`. |
| ro | Romanian | Latin | 🟢 | 🟢 | ș/ț cedilla vs comma codepoint variants. |
| ru | Russian | Cyrillic | 🟢 | 🟢 | — |
| sk | Slovak | Latin | 🟢 | 🟢 | — |
| sl | Slovenian | Latin | 🟢 | 🟢 | — |
| sq | Albanian | Latin | 🟢 | 🟢 | Digraphs (`dh`, `gj`, `ll`) are fine as tokens. |
| sv | Swedish | Latin | 🟢 | 🟢 | Compounds. |
| tl | Tagalog | Latin | 🟢 | 🟢 | Reduplication. |
| uk | Ukrainian | Cyrillic | 🟢 | 🟢 | Apostrophe `'` is a letter modifier, kept internal. |

### Tier 2 — frequency works, proper nouns inert (caseless, space-separated)

Word counting is fine; the script has no case, so proper-noun detection does
nothing.

| Code | Language | Script | Freq | PN | Difficulties / notes |
|---|---|---|---|---|---|
| ar | Arabic | Arabic | 🟢 | ⚪ | Clitics (`و`, `ال`, prepositions) attach to words; RTL (no effect on counts); usually no short-vowel diacritics. |
| bn | Bengali | Bengali | 🟢 | ⚪ | Complex conjuncts; ZWJ/ZWNJ inside clusters. |
| he | Hebrew | Hebrew | 🟢 | ⚪ | Prefix clitics (`ה`, `ו`, `ב`) attach; RTL; no niqqud. |
| hi | Hindi | Devanagari | 🟢 | ⚪ | — |
| ka | Georgian | Georgian | 🟢 | ⚪ | Mkhedruli is unicameral (no case at all). |
| ko | Korean | Hangul | 🟢 | ⚪ | Tokens are *eojeol* (word + attached particles), not lemmas. |
| ml | Malayalam | Malayalam | 🟢 | ⚪ | Agglutinative; complex script. |
| si | Sinhala | Sinhala | 🟢 | ⚪ | — |
| ta | Tamil | Tamil | 🟢 | ⚪ | Agglutinative. |
| te | Telugu | Telugu | 🟢 | ⚪ | Agglutinative. |

### Tier 2.5 — cased/spaced but defeated by a language rule

Output is produced, but a specific rule makes it materially wrong; needs
language-aware handling. German, Turkish, and Serbian are handled by
`--language`; the rest are still open.

| Code | Language | Script | Freq | PN | Difficulties / notes |
|---|---|---|---|---|---|
| de | German | Latin | 🟢 | 🟠 | **All nouns are capitalised**, not just proper nouns, so the heuristic is useless; `--language de` auto-disables proper-noun detection. Frequency is fine. |
| tr | Turkish | Latin | 🟢 | 🟢 | Pass `--language tr` for correct dotted/dotless i casing (`I→ı`, `İ→i`); without it forms get corrupted/merged. |
| vi | Vietnamese | Latin | 🟡 | 🟢 | Spaces separate **syllables**, not words; counts are syllable-level, so multi-syllable words are fragmented. |
| sr | Serbian | Cyrillic + Latin | 🟢 | 🟢 | Pass `--language sr` to transliterate Cyrillic→Latin so both spellings of a word merge into one count. |
| fa | Persian | Arabic | 🟡 | ⚪ | ZWNJ (`‌`) inside words is segmented inconsistently, splitting morphemes; caseless. |
| ur | Urdu | Arabic | 🟡 | ⚪ | As Persian: ZWNJ handling; RTL; caseless. |

### Tier 3 — broken (no spaces between words)

UAX #29 cannot find word boundaries without a dictionary; output is per-character
(CJK) or per-syllable (Thai). Requires a dedicated segmenter (`jieba` for
Chinese, MeCab / `lindera` for Japanese, ICU / PyThaiNLP for Thai).

| Code | Language | Script | Freq | PN | Difficulties / notes |
|---|---|---|---|---|---|
| ja | Japanese | Kanji + Kana | 🔴 | ⛔ | No spaces; mixed scripts. Needs morphological analyser. |
| th | Thai | Thai | 🔴 | ⛔ | No spaces; verified to split into syllables/fragments. |
| zh_cn | Chinese (Simplified) | Han | 🔴 | ⛔ | No spaces; verified to split into single characters. |
| zh_tw | Chinese (Traditional) | Han | 🔴 | ⛔ | As `zh_cn`. |

### Special — not monolingual

`ze_en` and `ze_zh` are dual-subtitle files (two languages per line), not
monolingual targets.

### Summary

Of the 60 monolingual languages: **39** are Tier 1 (full support, no work
needed); **10** are Tier 2 (good frequency lists, proper-noun detection inert);
**6** are Tier 2.5 (need a small language-specific fix), of which German,
Turkish, and Serbian are now handled by `--language`, leaving Vietnamese,
Persian, and Urdu open; and **4** (3 languages — Chinese simplified + traditional,
Japanese, Thai) are Tier 3 and need a real word segmenter. Note that Emmio
already registers Chinese and Japanese, both Tier 3 — their lists should not come
from this tool without a segmenter.

Languages with a `--language` rule (English, German, Turkish, Serbian; plus
Armenian and Greek sentence punctuation handled automatically) should be run with
the flag set for correct results.

## Notes

- Tokenisation follows Unicode UAX #29 word boundaries, so accented letters and
  non-Latin scripts work, and clitics like French `c'est` are kept as a single
  token. (FrequencyWords splits on the apostrophe instead — adjust if exact
  parity is required.)
- Licence: OPUS / OpenSubtitles data is for research and personal use; attribute
  OPUS and OpenSubtitles.org when redistributing derived lists.
