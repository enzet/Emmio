"""Self-reported language knowledge: curated assessment kinds and values.

A user may log a proficiency estimate for a language at any time — not
Emmio's own computed lexicon rate, but a self-report they enter by hand,
e.g. "French, B2, DELF/DALF, 2022-06-01". Each estimate names a *kind*
(native speaker, self-assessed, teacher-assessed, or a specific certifying
organization) first, which then determines the scale its *value* is drawn
from: some organizations use CEFR labels, others their own (TestDaF's TDN
3-5, HSK's 1-9, ...), and a few report a bare number (IELTS, TOEFL iBT).
Mirrors the `CategoryNode`/`NOT_TO_CHECK_TREE` pattern in
`emmio.lexicon.core`: a single source of truth, exposed over the API so the
web client never hardcodes the taxonomy.
"""

import math
from datetime import UTC, date, datetime
from typing import NamedTuple


class KnowledgeValue(NamedTuple):
    """One selectable value on a knowledge kind's scale."""

    code: str
    """Stored in `language_knowledge_records.value`, e.g. `B2`, `N1`."""

    label: str
    """Human-readable label shown in the picker."""


class NumericRange(NamedTuple):
    """A continuous numeric scale, sampled at fixed steps (e.g. IELTS)."""

    minimum: float
    maximum: float
    step: float


class KnowledgeKind(NamedTuple):
    """One assessment kind: who or what produced the estimate.

    Exactly one of `values` (non-empty) or `numeric_range` describes the
    kind's scale, except `native` and any kind with `allows_other` and
    neither `values` nor `numeric_range` (e.g. `standardized_test`), which
    take free text instead — see `is_valid_knowledge_value`.
    """

    code: str
    """Stored in `language_knowledge_records.kind`."""

    label: str
    """Human-readable name, e.g. `DELF / DALF`."""

    languages: tuple[str, ...] | None
    """ISO 639-1 codes this kind applies to, or `None` for any language."""

    values: tuple[KnowledgeValue, ...] = ()
    """Valid discrete values, or `()` if `numeric_range` is set instead."""

    numeric_range: NumericRange | None = None
    """Valid continuous range, or `None` if `values` is set instead."""

    allows_other: bool = False
    """Whether a value outside `values` may be entered as free text.

    With no curated `values` and no `numeric_range` (`standardized_test`),
    this makes the whole value field free text; alongside a `values` list,
    it adds an "Other" escape hatch next to the curated choices, for a real
    result that just doesn't land on one of the listed values.
    """

    has_caption: bool = False
    """Whether this kind needs a free-text caption naming it more precisely.

    `standardized_test` is deliberately generic (unlike a specific curated
    organization), so it captures which test in a `language_knowledge_
    records.caption` free-text field instead of a fixed label.
    """

    requires_date: bool = True
    """Whether this kind needs a self-reported date.

    False only for `native`: a learner does not become native "as of" some
    date the way a certificate or self-assessment is dated, so the date
    field is dropped rather than asking for an arbitrary one.
    """

    implicit_date: bool = False
    """Whether the date is always "now", so the user is not asked for it.

    A certificate is dated by whoever issued it, and could have been earned
    years ago, so the date is a real question. A self-assessment is not: you
    are assessing yourself *today*, which makes asking pure friction — the
    record is still dated (`requires_date` stays True, and the history is
    only meaningful with dates), the date is just filled in rather than
    typed. See `resolve_knowledge_date`.
    """


_CEFR: tuple[KnowledgeValue, ...] = (
    KnowledgeValue("A1", "A1"),
    KnowledgeValue("A2", "A2"),
    KnowledgeValue("B1", "B1"),
    KnowledgeValue("B2", "B2"),
    KnowledgeValue("C1", "C1"),
    KnowledgeValue("C2", "C2"),
)


# The curated list of assessment kinds. Extend by adding a row — nothing
# else needs to change, the API and web picker both derive from this. Every
# kind with a curated `values` list also sets `allows_other=True`: a real
# result that doesn't land on one of the listed values (an old exam version,
# an unlisted grade, ...) should still be recordable as free text rather
# than forced onto the nearest curated value.
KNOWLEDGE_KINDS: tuple[KnowledgeKind, ...] = (
    KnowledgeKind("native", "Native speaker", None, requires_date=False),
    KnowledgeKind(
        "self",
        "Self-assessed",
        None,
        _CEFR,
        allows_other=True,
        implicit_date=True,
    ),
    KnowledgeKind(
        "teacher", "Teacher-assessed", None, _CEFR, allows_other=True
    ),
    KnowledgeKind(
        "delf_dalf", "DELF / DALF", ("fr",), _CEFR, allows_other=True
    ),
    KnowledgeKind(
        "goethe", "Goethe-Zertifikat", ("de",), _CEFR, allows_other=True
    ),
    KnowledgeKind(
        "testdaf",
        "TestDaF",
        ("de",),
        (
            KnowledgeValue("TDN3", "TDN 3"),
            KnowledgeValue("TDN4", "TDN 4"),
            KnowledgeValue("TDN5", "TDN 5"),
        ),
        allows_other=True,
    ),
    KnowledgeKind("dele", "DELE", ("es",), _CEFR, allows_other=True),
    KnowledgeKind(
        "torfl",
        "TORFL",
        ("ru",),
        (
            KnowledgeValue("teu", "Elementary (ТЭУ)"),
            KnowledgeValue("tbu", "Basic (ТБУ)"),
            KnowledgeValue("trki1", "TRKI-1"),
            KnowledgeValue("trki2", "TRKI-2"),
            KnowledgeValue("trki3", "TRKI-3"),
            KnowledgeValue("trki4", "TRKI-4"),
        ),
        allows_other=True,
    ),
    KnowledgeKind(
        "ielts", "IELTS", ("en",), numeric_range=NumericRange(1.0, 9.0, 0.5)
    ),
    KnowledgeKind(
        "toefl",
        "TOEFL iBT",
        ("en",),
        numeric_range=NumericRange(0.0, 120.0, 1.0),
    ),
    KnowledgeKind(
        "cambridge",
        "Cambridge English",
        ("en",),
        (
            KnowledgeValue("ket", "A2 Key"),
            KnowledgeValue("pet", "B1 Preliminary"),
            KnowledgeValue("fce", "B2 First"),
            KnowledgeValue("cae", "C1 Advanced"),
            KnowledgeValue("cpe", "C2 Proficiency"),
        ),
        allows_other=True,
    ),
    KnowledgeKind(
        "hsk",
        "HSK",
        ("zh",),
        tuple(KnowledgeValue(str(n), f"HSK {n}") for n in range(1, 10)),
        allows_other=True,
    ),
    KnowledgeKind(
        "jlpt",
        "JLPT",
        ("ja",),
        tuple(KnowledgeValue(f"N{n}", f"N{n}") for n in range(5, 0, -1)),
        allows_other=True,
    ),
    KnowledgeKind(
        "topik",
        "TOPIK",
        ("ko",),
        tuple(KnowledgeValue(str(n), f"Level {n}") for n in range(1, 7)),
        allows_other=True,
    ),
    KnowledgeKind(
        "standardized_test",
        "Standardized test",
        None,
        allows_other=True,
        has_caption=True,
    ),
)

KNOWLEDGE_KINDS_BY_CODE: dict[str, KnowledgeKind] = {
    kind.code: kind for kind in KNOWLEDGE_KINDS
}


def is_valid_knowledge_value(kind: KnowledgeKind, value: str | None) -> bool:
    """Check whether `value` is valid on `kind`'s scale.

    :param kind: the chosen assessment kind
    :param value: the submitted value, or `None`
    """
    if kind.numeric_range is not None:
        if value is None:
            return False
        try:
            number = float(value)
        except ValueError:
            return False
        lo, hi, step = kind.numeric_range
        if not lo <= number <= hi:
            return False
        steps = round((number - lo) / step)
        return math.isclose(lo + steps * step, number, abs_tol=1e-9)
    if any(candidate.code == value for candidate in kind.values):
        return True
    if kind.allows_other:
        # Free text instead of (or, with no curated `values` at all, in
        # place of) one of the listed values.
        return bool(value and value.strip())
    if not kind.values:
        return value is None  # E.g. `native`: no value scale at all.
    return False


def is_valid_caption(kind: KnowledgeKind, caption: str | None) -> bool:
    """Check whether `caption` is valid for `kind`.

    :param kind: the chosen assessment kind
    :param caption: the submitted caption, or `None`
    """
    if kind.has_caption:
        return bool(caption and caption.strip())
    return caption is None


def is_valid_knowledge_date(kind: KnowledgeKind, date_: date | None) -> bool:
    """Check whether `date_` is valid for `kind`.

    :param kind: the chosen assessment kind
    :param date_: the submitted date, or `None`
    """
    if not kind.requires_date:
        return date_ is None
    if kind.implicit_date:
        # `None` is the expected case (the client is not asked for a date);
        # an explicit one is still accepted, so a caller that knows when the
        # assessment happened can say so.
        return True
    return date_ is not None


def resolve_knowledge_date(
    kind: KnowledgeKind, date_: date | None
) -> date | None:
    """Fill in the date for a kind that does not ask for one.

    :param kind: the chosen assessment kind
    :param date_: the submitted date, or `None`
    :return: the date to store — today for an `implicit_date` kind given
        nothing, otherwise `date_` unchanged
    """
    if kind.requires_date and kind.implicit_date and date_ is None:
        return datetime.now(UTC).date()
    return date_
