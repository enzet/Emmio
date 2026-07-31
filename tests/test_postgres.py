"""Tests for frequency-list curation storage (`emmio.postgres`).

Runs against the real `emmio_test` database (see `tests/conftest.py`), which
is truncated before every test — these are integration tests, not mocks.
"""

import pytest

from emmio import postgres


def _make_list(n_strata: int = 10) -> int:
    """Create a fresh curated list for these tests."""

    return postgres.create_curated_list(
        "fr", "fr_frequency_words_2018", "French OST 2018 Curated", n_strata
    )


def _make_user(user_id: str) -> None:
    postgres.ensure_user(user_id, user_id)


def test_create_curated_list_is_idempotent() -> None:
    """Calling `create_curated_list` twice returns the same identifier."""

    first = _make_list()
    second = postgres.create_curated_list(
        "fr", "fr_frequency_words_2018", "French OST 2018 Curated"
    )
    assert first == second


def test_get_curated_list_id_missing_returns_none() -> None:
    """A list that was never created is reported as absent, not an error."""

    assert postgres.get_curated_list_id("fr", "fr_frequency_words_2018") is None
    _make_list()
    found = postgres.get_curated_list_id("fr", "fr_frequency_words_2018")
    assert found is not None


def test_add_curated_words_is_idempotent() -> None:
    """Re-adding an existing word does not reset its state."""

    list_id = _make_list()
    postgres.add_curated_words(
        list_id, [("chat", 0, 0, "bootstrap"), ("chien", 0, 1, "bootstrap")]
    )
    _make_user("alice")
    postgres.record_curation_vote(list_id, "chat", "W", "alice")

    # Re-running the bootstrap insert must not reset "chat"'s vote.
    postgres.add_curated_words(list_id, [("chat", 0, 0, "bootstrap")])

    words = postgres.get_curated_words(list_id)
    chat = next(w for w in words if w[0] == "chat")
    assert chat[3] == "W"  # category
    assert chat[4] == 1  # votes


def test_get_curated_words_orders_by_stratum_then_panel_order() -> None:
    """Words come back grouped by stratum, in their fixed serving order."""

    list_id = _make_list()
    postgres.add_curated_words(
        list_id,
        [
            ("b", 1, 1, "bootstrap"),
            ("a", 1, 0, "bootstrap"),
            ("z", 0, 0, "bootstrap"),
        ],
    )
    words = postgres.get_curated_words(list_id)
    assert [w[0] for w in words] == ["z", "a", "b"]


def test_get_curated_words_filters_by_stratum() -> None:
    """Restricting to one stratum excludes the others."""

    list_id = _make_list()
    postgres.add_curated_words(
        list_id, [("a", 0, 0, "bootstrap"), ("b", 1, 0, "bootstrap")]
    )
    assert [w[0] for w in postgres.get_curated_words(list_id, stratum=1)] == [
        "b"
    ]


def test_promote_fallback_word_appends_after_current_max() -> None:
    """A promoted word gets the next panel_order in its stratum."""

    list_id = _make_list()
    postgres.add_curated_words(
        list_id, [("a", 0, 0, "bootstrap"), ("b", 0, 1, "bootstrap")]
    )
    added = postgres.promote_fallback_word(list_id, "c", stratum=0)
    assert added is True

    words = postgres.get_curated_words(list_id, stratum=0)
    c = next(w for w in words if w[0] == "c")
    assert c[1] == 0  # stratum
    assert c[2] == 2  # panel_order, after "a" (0) and "b" (1)
    assert c[3] == "U"  # unknown, pending review


def test_promote_fallback_word_is_a_no_op_if_already_present() -> None:
    """Promoting an already-curated word changes nothing and reports so."""

    list_id = _make_list()
    postgres.add_curated_words(list_id, [("a", 0, 0, "bootstrap")])
    added = postgres.promote_fallback_word(list_id, "a", stratum=0)
    assert added is False
    assert len(postgres.get_curated_words(list_id)) == 1


def test_promote_fallback_word_first_in_empty_stratum_is_order_zero() -> None:
    """The first word ever added to a stratum gets panel_order 0."""

    list_id = _make_list()
    postgres.promote_fallback_word(list_id, "first", stratum=3)
    words = postgres.get_curated_words(list_id, stratum=3)
    assert words[0][2] == 0


def test_record_curation_vote_unknown_word_raises() -> None:
    """Voting on a word never added to the list is a usage error."""

    list_id = _make_list()
    _make_user("alice")
    with pytest.raises(ValueError, match="ghost"):
        postgres.record_curation_vote(list_id, "ghost", "W", "alice")


def test_record_curation_vote_single_vote_is_full_agreement() -> None:
    """One vote is unanimous by definition: votes=1, agreement=1.0."""

    list_id = _make_list()
    postgres.add_curated_words(list_id, [("chat", 0, 0, "bootstrap")])
    _make_user("alice")
    postgres.record_curation_vote(list_id, "chat", "W", "alice")

    word = postgres.get_curated_words(list_id)[0]
    _, _, _, category, votes, agreement = word
    assert category == "W"
    assert votes == 1
    assert agreement == 1.0


def test_record_curation_vote_majority_wins() -> None:
    """The consensus category is the mode across curators' latest votes."""

    list_id = _make_list()
    postgres.add_curated_words(list_id, [("chat", 0, 0, "bootstrap")])
    for name in ("alice", "bob", "carol"):
        _make_user(name)
    postgres.record_curation_vote(list_id, "chat", "W", "alice")
    postgres.record_curation_vote(list_id, "chat", "W", "bob")
    postgres.record_curation_vote(list_id, "chat", "N", "carol")

    _, _, _, category, votes, agreement = postgres.get_curated_words(list_id)[0]
    assert category == "W"
    assert votes == 3
    assert agreement == pytest.approx(2 / 3)


def test_record_curation_vote_revote_updates_not_duplicates() -> None:
    """A curator changing their mind updates their vote, not adds a second."""

    list_id = _make_list()
    postgres.add_curated_words(list_id, [("chat", 0, 0, "bootstrap")])
    _make_user("alice")
    _make_user("bob")
    postgres.record_curation_vote(list_id, "chat", "N", "alice")
    postgres.record_curation_vote(list_id, "chat", "W", "bob")
    # Alice reconsiders.
    postgres.record_curation_vote(list_id, "chat", "W", "alice")

    _, _, _, category, votes, agreement = postgres.get_curated_words(list_id)[0]
    assert category == "W"
    assert votes == 2  # Still two distinct curators, not three votes.
    assert agreement == 1.0


def test_get_next_curation_candidate_skips_already_voted() -> None:
    """A curator is never offered a word they already voted on."""

    list_id = _make_list()
    postgres.add_curated_words(
        list_id, [("chat", 0, 0, "bootstrap"), ("chien", 0, 1, "bootstrap")]
    )
    _make_user("alice")
    postgres.record_curation_vote(list_id, "chat", "W", "alice")

    assert postgres.get_next_curation_candidate(list_id, "alice") == "chien"


def test_get_next_curation_candidate_prefers_fewest_votes() -> None:
    """Coverage first: an untouched word beats one with an existing vote."""

    list_id = _make_list()
    postgres.add_curated_words(
        list_id, [("chat", 0, 0, "bootstrap"), ("chien", 0, 1, "bootstrap")]
    )
    _make_user("alice")
    _make_user("bob")
    postgres.record_curation_vote(list_id, "chat", "W", "alice")

    # Bob has voted on neither; "chien" (0 votes) should win over "chat" (1).
    assert postgres.get_next_curation_candidate(list_id, "bob") == "chien"


def test_get_next_curation_candidate_respects_stratum() -> None:
    """Restricting to a stratum only offers words from that stratum."""

    list_id = _make_list()
    postgres.add_curated_words(
        list_id, [("a", 0, 0, "bootstrap"), ("b", 1, 0, "bootstrap")]
    )
    _make_user("alice")
    assert (
        postgres.get_next_curation_candidate(list_id, "alice", stratum=1) == "b"
    )


def test_get_next_curation_candidate_none_left_returns_none() -> None:
    """A curator who has voted on everything gets `None`, not an error."""

    list_id = _make_list()
    postgres.add_curated_words(list_id, [("chat", 0, 0, "bootstrap")])
    _make_user("alice")
    postgres.record_curation_vote(list_id, "chat", "W", "alice")
    assert postgres.get_next_curation_candidate(list_id, "alice") is None
