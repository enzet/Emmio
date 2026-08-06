//! Frequency list generator for OpenSubtitles (OPUS) monolingual dumps.
//!
//! Reads a plain-text or gzip-compressed corpus (one sentence per line, as
//! distributed by OPUS), tokenises it with Unicode word segmentation, counts
//! occurrences, and writes a frequency list as `word count cap_ratio` per
//! line, sorted from most to least frequent. The first two fields match the
//! format used by the FrequencyWords project; `cap_ratio` (see below) is
//! appended as a third field, `NA` if the word never occurs outside a
//! sentence start, or omitted entirely for a language where the field
//! wouldn't mean anything (see `proper_nouns_supported`) — `NA` on every
//! single line would just be confusing noise, not data.
//!
//! Optionally it also tracks per-word capitalization and guesses which words are
//! proper nouns. The signal is *capitalization away from sentence start*: every
//! word is capitalized at the start of a sentence, so that position is
//! uninformative; a word that stays title-cased mid-sentence (`Paris`) is likely
//! a proper noun, whereas one that is only capitalized sentence-initially (`the`,
//! `je`) is not.
//!
//! This is a Unicode-aware replacement for `c/text.c`, which only recognised
//! ASCII and Armenian letters.

use std::borrow::Cow;
use std::cell::Cell;
use std::collections::HashMap;
use std::fs::File;
use std::io::{self, BufRead, BufReader, BufWriter, IsTerminal, Read, Write};
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::time::{Duration, Instant};

use clap::{Parser, ValueEnum};
use flate2::read::MultiGzDecoder;
use unicode_segmentation::UnicodeSegmentation;

/// Generate a frequency list from a monolingual corpus.
#[derive(Parser)]
#[command(version, about)]
struct Args {
    /// Input corpus. Plain text or gzip; `.gz` files are decompressed on the
    /// fly.
    #[arg(short, long)]
    input: PathBuf,

    /// Output frequency list (`word count cap_ratio` per line, most frequent
    /// first).
    #[arg(short, long)]
    output: PathBuf,

    /// Also write a TSV capitalization report (`word total titlecased
    /// sentence_initial cap_ratio is_proper_noun`) to this path.
    #[arg(long)]
    stats: Option<PathBuf>,

    /// Also write a copy of the output restricted to words with
    /// `cap_ratio >= 0.2` to this path (same `word count cap_ratio` format).
    /// Words with an undefined `cap_ratio` (`NA`) are excluded. A quick way
    /// to review proper-noun/honorific-noun candidates without the bulk of
    /// the full list.
    #[arg(long)]
    output_cap: Option<PathBuf>,

    /// ISO code (e.g. `tr`, `de`, `hy`) enabling language-specific casing and
    /// proper-noun rules. Optional; without it, generic Unicode rules apply.
    #[arg(short, long)]
    language: Option<String>,

    /// Corpus type. `subtitles` additionally drops whole lines that are
    /// bracketed annotations like `[door creaks]`.
    #[arg(short = 't', long = "type", value_enum, default_value_t = CorpusType::Plain)]
    corpus_type: CorpusType,

    /// Drop words occurring fewer than this many times.
    #[arg(long, default_value_t = 1)]
    min_count: u64,

    /// Keep tokens containing digits (dropped by default).
    #[arg(long)]
    keep_numbers: bool,

    /// Do not lowercase tokens (case-folding is on by default).
    #[arg(long)]
    keep_case: bool,

    /// Fraction of *non-sentence-initial* occurrences that must be title-cased
    /// for a word to be flagged as a proper noun. Default chosen empirically:
    /// it maximizes F1 against dictionary-labeled ground truth on a real
    /// OpenSubtitles English sample (0.5 yields ~46% false positives, mostly
    /// honorific address terms).
    #[arg(long, default_value_t = 0.8)]
    proper_noun_threshold: f64,

    /// Minimum number of non-sentence-initial occurrences before a word may be
    /// flagged as a proper noun (guards against noise from rare words).
    #[arg(long, default_value_t = 5)]
    proper_noun_min_count: u64,

    /// Stop after counting this many words. Checked after each line, so the
    /// final line is processed in full rather than cut off mid-sentence.
    #[arg(long)]
    stop_at: Option<u64>,
}

/// Source format of the corpus, selecting format-specific line filtering.
#[derive(Clone, Copy, PartialEq, Eq, Default, ValueEnum)]
enum CorpusType {
    /// Plain text; every line is treated as content.
    #[default]
    Plain,
    /// Subtitles; bracketed annotation lines like `[door creaks]` are dropped.
    Subtitles,
}

/// Whether a line should be skipped for the given corpus type.
///
/// In subtitle corpora a line that is wholly bracketed (`[applause]`,
/// `[music playing]`) describes sound rather than speech and is not vocabulary.
/// A line with only a leading speaker tag (`[John] Hello`) is kept, since it
/// still contains dialogue.
fn is_skipped_line(line: &str, corpus_type: CorpusType) -> bool {
    if corpus_type != CorpusType::Subtitles {
        return false;
    }
    let trimmed = line.trim();
    trimmed.starts_with('[') && trimmed.ends_with(']')
}

/// Per-word counters accumulated over the corpus.
#[derive(Default)]
struct WordStats {
    /// Total occurrences (under the case-folded key).
    total: u64,
    /// Occurrences whose surface form is title case (first letter upper, no
    /// other uppercase letter), e.g. `Paris`, `I'm`.
    titlecased: u64,
    /// Occurrences at the start of a sentence (first word, or after `.!?…`).
    sentence_initial: u64,
    /// Title-cased occurrences that are *not* at a sentence start — the proper
    /// noun signal.
    titlecased_off_start: u64,
}

impl WordStats {
    /// Occurrences not at a sentence start. These are the only ones whose
    /// capitalization is informative.
    fn off_start(&self) -> u64 {
        self.total - self.sentence_initial
    }

    /// Fraction of off-start occurrences that are title-cased, or `None` when
    /// the word never appears off the sentence start.
    fn cap_ratio(&self) -> Option<f64> {
        let off_start = self.off_start();
        (off_start > 0).then(|| self.titlecased_off_start as f64 / off_start as f64)
    }

    /// Whether/what to print in the primary output's `cap_ratio` field.
    ///
    /// Outer `None` when the proper-noun heuristic is disabled for this
    /// language (see `proper_nouns_supported`, e.g. German, where every
    /// noun is capitalized): the field is dropped from that line entirely,
    /// rather than printing a `cap_ratio` that would read `NA` on every
    /// single word — that's not data, just confusing noise dressed up as a
    /// column. `Some(None)`/`Some(Some(ratio))` otherwise, exactly
    /// `cap_ratio()`'s own per-word `None` (never occurs off a sentence
    /// start)/`Some`.
    fn output_cap_ratio(&self, proper_nouns_enabled: bool) -> Option<Option<f64>> {
        proper_nouns_enabled.then(|| self.cap_ratio())
    }

    /// Whether the word looks like a proper noun under the given thresholds.
    fn is_proper_noun(&self, threshold: f64, min_count: u64) -> bool {
        self.off_start() >= min_count
            && self.cap_ratio().is_some_and(|ratio| ratio >= threshold)
    }
}

/// A reader wrapper that tallies bytes as they are read, for progress
/// reporting. Counts against `inner` directly, so wrapping the raw file
/// (below any gzip decoding) tracks progress through the file on disk
/// rather than through the (unknown ahead of time) decompressed size.
struct CountingReader<R> {
    inner: R,
    count: Rc<Cell<u64>>,
}

impl<R: Read> Read for CountingReader<R> {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        let n = self.inner.read(buf)?;
        self.count.set(self.count.get() + n as u64);
        Ok(n)
    }
}

/// Open the input as a line reader, transparently decompressing `.gz`.
///
/// Also returns a live byte counter (bytes consumed from the file on disk,
/// before decompression) and the file's total size, so the caller can report
/// progress through the input regardless of whether it is compressed.
fn open_input(path: &Path) -> io::Result<(Box<dyn BufRead>, Rc<Cell<u64>>, u64)> {
    let file = File::open(path)?;
    let total_size = file.metadata()?.len();
    let bytes_read = Rc::new(Cell::new(0u64));
    let counting = CountingReader {
        inner: file,
        count: Rc::clone(&bytes_read),
    };
    let is_gzip = path.extension().is_some_and(|e| e == "gz");
    let reader: Box<dyn Read> = if is_gzip {
        Box::new(MultiGzDecoder::new(counting))
    } else {
        Box::new(counting)
    };
    Ok((
        Box::new(BufReader::with_capacity(1 << 20, reader)),
        bytes_read,
        total_size,
    ))
}

/// Print a single-line, in-place progress update to stderr.
fn print_progress(lines: u64, unique_words: usize, bytes_read: u64, total_size: u64, elapsed: Duration) {
    let rate = lines as f64 / elapsed.as_secs_f64().max(0.001);
    let pct = if total_size > 0 {
        format!("{:5.1}%", (bytes_read as f64 / total_size as f64 * 100.0).min(100.0))
    } else {
        "  ?  ".to_string()
    };
    eprint!("\r\x1b[K{pct}  {lines} lines  {unique_words} unique words  {rate:.0} lines/s");
    let _ = io::stderr().flush();
}

/// Decide whether a segmented token should be counted.
///
/// A token is kept when it contains at least one alphabetic character and,
/// unless `keep_numbers` is set, no digits. This mirrors the FrequencyWords
/// convention of keeping word-like tokens and discarding pure punctuation and
/// numerals.
fn is_word(token: &str, keep_numbers: bool) -> bool {
    let mut has_alpha = false;
    for c in token.chars() {
        if c.is_alphabetic() {
            has_alpha = true;
        } else if c.is_numeric() && !keep_numbers {
            return false;
        }
    }
    has_alpha
}

/// Whether a token is title case: first letter uppercase, no other uppercase
/// letter (so `Paris` and `I'm` qualify, but `PARIS` and `iPhone` do not).
fn is_titlecase(token: &str) -> bool {
    let mut chars = token.chars();
    match chars.next() {
        Some(first) if first.is_uppercase() => !chars.any(|c| c.is_uppercase()),
        _ => false,
    }
}

/// Whether a non-word segment ends a sentence — or otherwise starts a new
/// capitalization context, so the next word is uninformative for the
/// proper-noun heuristic even though it is not a new grammatical sentence.
///
/// Covers Latin `.!?`, the ellipsis, fullwidth CJK forms, the Armenian full
/// stop `։` and question `՞`, the Greek question mark `;` (U+037E), the
/// colon and opening double quotes/guillemets (French and English both
/// capitalize the first word of quoted direct speech they introduce, e.g.
/// `Il a dit : "Écoute..."`, even mid-sentence), and em/en dashes (used for
/// dialogue turns and set-off exclamations, e.g. `Hé — Écoutez —`).
/// Deliberately excludes single quotes/apostrophes (`'`, `’`): both
/// languages use them inside word-internal contractions (`j'ai`, `l'écoute`,
/// `don't`), so treating them as a reset would misfire on ordinary words —
/// unlike double quotes, which are unambiguous dialogue delimiters.
fn ends_sentence(segment: &str) -> bool {
    segment.contains([
        '.', '!', '?', '…', '。', '！', '？', '\u{0589}', '\u{055E}', '\u{037E}', ':',
        '"', '«', '»', '\u{201C}', '\u{201D}', '—', '–',
    ])
}

/// Serbian Gaj's Latin equivalent of a Serbian Cyrillic letter, or `None` if the
/// character is not Serbian Cyrillic. The mapping is a deterministic bijection;
/// the digraph letters `љ њ џ` expand to two Latin characters.
fn serbian_cyrillic_to_latin(c: char) -> Option<&'static str> {
    Some(match c {
        'а' => "a", 'б' => "b", 'в' => "v", 'г' => "g", 'д' => "d",
        'ђ' => "đ", 'е' => "e", 'ж' => "ž", 'з' => "z", 'и' => "i",
        'ј' => "j", 'к' => "k", 'л' => "l", 'љ' => "lj", 'м' => "m",
        'н' => "n", 'њ' => "nj", 'о' => "o", 'п' => "p", 'р' => "r",
        'с' => "s", 'т' => "t", 'ћ' => "ć", 'у' => "u", 'ф' => "f",
        'х' => "h", 'ц' => "c", 'ч' => "č", 'џ' => "dž", 'ш' => "š",
        'А' => "A", 'Б' => "B", 'В' => "V", 'Г' => "G", 'Д' => "D",
        'Ђ' => "Đ", 'Е' => "E", 'Ж' => "Ž", 'З' => "Z", 'И' => "I",
        'Ј' => "J", 'К' => "K", 'Л' => "L", 'Љ' => "Lj", 'М' => "M",
        'Н' => "N", 'Њ' => "Nj", 'О' => "O", 'П' => "P", 'Р' => "R",
        'С' => "S", 'Т' => "T", 'Ћ' => "Ć", 'У' => "U", 'Ф' => "F",
        'Х' => "H", 'Ц' => "C", 'Ч' => "Č", 'Џ' => "Dž", 'Ш' => "Š",
        _ => return None,
    })
}

/// Transliterate any Serbian Cyrillic in a token to Latin, leaving other
/// characters untouched.
fn serbian_to_latin(token: &str) -> String {
    let mut out = String::with_capacity(token.len());
    for c in token.chars() {
        match serbian_cyrillic_to_latin(c) {
            Some(latin) => out.push_str(latin),
            None => out.push(c),
        }
    }
    out
}

/// Fold a token onto a single canonical script so the same word written in
/// different scripts is counted once.
///
/// Serbian is digraphic (Cyrillic and Latin); we canonicalise to Latin. Other
/// languages are returned unchanged (borrowed, no allocation).
fn canonicalize_script<'a>(token: &'a str, language: Option<&str>) -> Cow<'a, str> {
    let is_cyrillic = |c: char| ('\u{0400}'..='\u{04FF}').contains(&c);
    if language == Some("sr") && token.chars().any(is_cyrillic) {
        Cow::Owned(serbian_to_latin(token))
    } else {
        Cow::Borrowed(token)
    }
}

/// Case-fold a token, applying language-specific rules.
///
/// For Turkish and Azerbaijani the dotted/dotless I distinction must be honoured
/// (`I→ı`, `İ→i`); the generic Unicode fold would wrongly map `I→i`.
fn fold_case(token: &str, language: Option<&str>) -> String {
    match language {
        Some("tr") | Some("az") => token
            .chars()
            .map(|c| match c {
                'I' => 'ı',
                'İ' => 'i',
                other => other,
            })
            .collect::<String>()
            .to_lowercase(),
        // `to_lowercase` is Unicode-aware (e.g. handles ß, İ).
        _ => token.to_lowercase(),
    }
}

/// Whether the proper-noun heuristic is meaningful for a language.
///
/// German capitalises *all* nouns, not just proper ones, so the signal is
/// useless there and detection is disabled.
fn proper_nouns_supported(language: Option<&str>) -> bool {
    language != Some("de")
}

/// Whether a flagged word should be suppressed as a known false positive.
///
/// In English the pronoun `I` is always capitalised mid-sentence.
fn is_false_positive(word: &str, language: Option<&str>) -> bool {
    language == Some("en") && word == "i"
}

fn run(args: &Args) -> io::Result<()> {
    let language = args.language.as_deref().map(str::to_ascii_lowercase);
    let language = language.as_deref();

    let mut counts: HashMap<String, WordStats> = HashMap::new();
    let (reader, bytes_read, total_size) = open_input(&args.input)?;

    let show_progress = io::stderr().is_terminal();
    let start = Instant::now();
    let mut last_print = start;

    let mut lines: u64 = 0;
    let mut words: u64 = 0;
    for line in reader.lines() {
        let line = line?;
        if is_skipped_line(&line, args.corpus_type) {
            continue;
        }
        // The first word of a line starts a sentence.
        let mut at_sentence_start = true;
        // Whether the current position is inside a `[...]` speaker tag or
        // sound annotation (subtitles only, e.g. `[Rodolphe] Écoutez-moi`).
        // Its contents are not dialogue: they must not be counted as words
        // and must not consume `at_sentence_start`, or the real first word
        // of the line is wrongly scored as non-initial.
        let mut in_bracket_tag = false;
        // `split_word_bounds` keeps punctuation segments (unlike `unicode_words`)
        // so we can track sentence boundaries within a line.
        for segment in line.split_word_bounds() {
            if args.corpus_type == CorpusType::Subtitles {
                if segment.contains('[') {
                    in_bracket_tag = true;
                }
                if in_bracket_tag {
                    if segment.contains(']') {
                        in_bracket_tag = false;
                    }
                    continue;
                }
            }
            if !is_word(segment, args.keep_numbers) {
                if ends_sentence(segment) {
                    at_sentence_start = true;
                }
                continue;
            }

            // Unify scripts first (e.g. Serbian Cyrillic→Latin), then case-fold.
            let canonical = canonicalize_script(segment, language);
            let key = if args.keep_case {
                canonical.into_owned()
            } else {
                fold_case(&canonical, language)
            };
            let stats = counts.entry(key).or_default();
            stats.total += 1;
            words += 1;
            let titlecased = is_titlecase(segment);
            if titlecased {
                stats.titlecased += 1;
            }
            if at_sentence_start {
                stats.sentence_initial += 1;
            } else if titlecased {
                stats.titlecased_off_start += 1;
            }
            at_sentence_start = false;
        }
        lines += 1;
        if show_progress {
            if lines % 10_000 == 0 {
                let now = Instant::now();
                if now.duration_since(last_print) >= Duration::from_millis(150) {
                    print_progress(lines, counts.len(), bytes_read.get(), total_size, start.elapsed());
                    last_print = now;
                }
            }
        } else if lines % 5_000_000 == 0 {
            eprintln!("Read {lines} lines, {} unique words...", counts.len());
        }
        if args.stop_at.is_some_and(|stop_at| words >= stop_at) {
            break;
        }
    }
    if show_progress {
        eprint!("\r\x1b[K");
        let _ = io::stderr().flush();
    }

    // Sort by descending count, breaking ties alphabetically for determinism.
    let mut sorted: Vec<(String, WordStats)> = counts
        .into_iter()
        .filter(|(_, s)| s.total >= args.min_count)
        .collect();
    sorted.sort_unstable_by(|a, b| b.1.total.cmp(&a.1.total).then_with(|| a.0.cmp(&b.0)));

    let proper_nouns_enabled = proper_nouns_supported(language);
    let mut writer = BufWriter::new(File::create(&args.output)?);
    let mut cap_writer = args
        .output_cap
        .as_ref()
        .map(|path| io::Result::Ok(BufWriter::new(File::create(path)?)))
        .transpose()?;
    for (word, stats) in &sorted {
        let Some(ratio) = stats.output_cap_ratio(proper_nouns_enabled) else {
            // Language where the heuristic is disabled: no `cap_ratio`
            // field at all, not one that would just always read `NA`.
            writeln!(writer, "{word} {}", stats.total)?;
            continue;
        };
        let cap_ratio = ratio.map_or_else(|| "NA".to_string(), |r| format!("{r:.2}"));
        writeln!(writer, "{word} {} {cap_ratio}", stats.total)?;
        if let Some(cap_writer) = &mut cap_writer {
            if ratio.is_some_and(|r| r >= 0.2) {
                writeln!(cap_writer, "{word} {} {cap_ratio}", stats.total)?;
            }
        }
    }
    writer.flush()?;
    if let Some(mut cap_writer) = cap_writer {
        cap_writer.flush()?;
    }

    if let Some(stats_path) = &args.stats {
        let mut proper_nouns = 0u64;
        let mut stats_writer = BufWriter::new(File::create(stats_path)?);
        writeln!(
            stats_writer,
            "word\ttotal\ttitlecased\tsentence_initial\tcap_ratio\tis_proper_noun"
        )?;
        for (word, stats) in &sorted {
            let is_proper = proper_nouns_enabled
                && !is_false_positive(word, language)
                && stats.is_proper_noun(args.proper_noun_threshold, args.proper_noun_min_count);
            proper_nouns += u64::from(is_proper);
            let ratio = stats
                .cap_ratio()
                .map_or_else(|| "NA".to_string(), |r| format!("{r:.3}"));
            writeln!(
                stats_writer,
                "{word}\t{}\t{}\t{}\t{ratio}\t{is_proper}",
                stats.total, stats.titlecased, stats.sentence_initial
            )?;
        }
        stats_writer.flush()?;
        if proper_nouns_enabled {
            eprintln!(
                "Wrote capitalization report to {} ({proper_nouns} proper nouns).",
                stats_path.display()
            );
        } else {
            eprintln!(
                "Wrote capitalization report to {} (proper-noun detection disabled \
                 for this language).",
                stats_path.display()
            );
        }
    }

    eprintln!(
        "Done: {lines} lines, {words} words read, {} unique words written to {}.",
        sorted.len(),
        args.output.display()
    );
    Ok(())
}

fn main() {
    let args = Args::parse();
    if let Err(error) = run(&args) {
        eprintln!("Error: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keeps_alphabetic_drops_punctuation_and_numbers() {
        assert!(is_word("café", false));
        assert!(is_word("don't", false));
        assert!(!is_word("123", false));
        assert!(!is_word("4k", false));
        assert!(is_word("4k", true));
    }

    #[test]
    fn titlecase_detection() {
        assert!(is_titlecase("Paris"));
        assert!(is_titlecase("I'm"));
        assert!(!is_titlecase("paris"));
        assert!(!is_titlecase("PARIS"));
        assert!(!is_titlecase("iPhone"));
    }

    #[test]
    fn turkish_casing_uses_dotless_i() {
        // Turkish: I→ı, İ→i; other letters fold normally.
        assert_eq!(fold_case("IŞIK", Some("tr")), "ışık");
        assert_eq!(fold_case("İSTANBUL", Some("tr")), "istanbul");
        // Generic folding maps I→i instead, losing the distinction.
        assert_eq!(fold_case("IŞIK", None), "işik");
    }

    #[test]
    fn subtitles_drop_bracketed_annotation_lines() {
        use CorpusType::{Plain, Subtitles};
        assert!(is_skipped_line("[door creaks]", Subtitles));
        assert!(is_skipped_line("  [music playing]  ", Subtitles));
        // A leading speaker tag is dialogue, not a pure annotation.
        assert!(!is_skipped_line("[John] Hello there", Subtitles));
        assert!(!is_skipped_line("Hello there", Subtitles));
        // Plain corpora keep everything.
        assert!(!is_skipped_line("[door creaks]", Plain));
    }

    #[test]
    fn serbian_cyrillic_and_latin_merge() {
        // Both scripts of "Beograd" canonicalise to the same Latin key.
        let from_cyrillic = fold_case(&canonicalize_script("Београд", Some("sr")), Some("sr"));
        let from_latin = fold_case(&canonicalize_script("Beograd", Some("sr")), Some("sr"));
        assert_eq!(from_cyrillic, "beograd");
        assert_eq!(from_latin, "beograd");
        // Digraph letters expand correctly: љ → lj.
        assert_eq!(serbian_to_latin("љубав"), "ljubav");
        // Non-Serbian languages are untouched.
        assert_eq!(canonicalize_script("Москва", Some("ru")), "Москва");
    }

    #[test]
    fn armenian_and_greek_sentence_ends() {
        assert!(ends_sentence("։")); // Armenian full stop.
        assert!(ends_sentence("\u{037E}")); // Greek question mark.
        assert!(!ends_sentence(","));
    }

    #[test]
    fn language_specific_proper_noun_rules() {
        assert!(!proper_nouns_supported(Some("de"))); // German: all nouns capitalised.
        assert!(proper_nouns_supported(Some("fr")));
        assert!(is_false_positive("i", Some("en"))); // English pronoun "I".
        assert!(!is_false_positive("i", Some("fr")));
    }

    #[test]
    fn proper_noun_uses_off_start_capitalization() {
        // Capitalized mostly off the sentence start: proper noun.
        let paris = WordStats {
            total: 10,
            titlecased: 10,
            sentence_initial: 2,
            titlecased_off_start: 8,
        };
        assert!(paris.is_proper_noun(0.5, 5));

        // Capitalized only at sentence start: not a proper noun.
        let the = WordStats {
            total: 100,
            titlecased: 20,
            sentence_initial: 20,
            titlecased_off_start: 0,
        };
        assert!(!the.is_proper_noun(0.5, 5));
    }

    #[test]
    fn output_cap_ratio_is_hidden_when_proper_nouns_are_unsupported() {
        // A German-style noun: capitalized every time off the sentence
        // start, same shape as `paris` above — but with the heuristic
        // disabled (as it would be for `language = Some("de")`), the
        // primary output must not carry that ratio at all.
        let fenster = WordStats {
            total: 10,
            titlecased: 10,
            sentence_initial: 2,
            titlecased_off_start: 8,
        };
        assert_eq!(fenster.output_cap_ratio(true), Some(fenster.cap_ratio()));
        assert_eq!(fenster.output_cap_ratio(false), None);
    }
}
