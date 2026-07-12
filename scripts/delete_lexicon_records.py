"""Delete wrong lexicon records from the PostgreSQL database.

Removes answer records from a user's lexicon (e.g. erroneous data entered
later), then rebuilds the derived `lexicon_words` state cache from the records
that remain and drops any word left with no records. All three steps run in one
transaction, so either everything succeeds or nothing changes.

`lexicon_records` is the source of truth; `lexicon_words` only caches each
word's latest state (`response`, `to_skip`, `last_seen`). Deleting records alone
would leave that cache stale, which this script fixes.

Dry run by default: it only reports what would be deleted. Pass `--apply` to
actually delete.

Usage:

    # preview records on/after a cutoff (UTC)
    python scripts/delete_lexicon_records.py --user enzet --lexicon fr \
        --after 2026-06-20

    # delete them for real
    python scripts/delete_lexicon_records.py --user enzet --lexicon fr \
        --after 2026-06-20 --apply

    # restrict to specific words (combine with --after or use alone)
    python scripts/delete_lexicon_records.py --user enzet --lexicon fr \
        --words foo bar --apply

The database connection string is taken from the `EMMIO_DATABASE_URL` or
`DATABASE_URL` environment variable (default: `postgresql:///emmio`).
"""

import argparse
import logging
from datetime import UTC, datetime
from typing import LiteralString

from emmio import postgres

logger: logging.Logger = logging.getLogger(__name__)

# Both queries below select the records to delete: a user's lexicon, optionally
# narrowed to records on/after a cutoff and/or to a set of words. A NULL filter
# parameter disables that filter, so the SQL is fixed (never built from user
# input). Shared parameter order: user, lexicon, after, after, words, words.

_COUNT_RECORDS: LiteralString = (
    "SELECT count(*), count(DISTINCT r.word_id) "
    "FROM lexicon_records r "
    "JOIN lexicon_words w ON w.id = r.word_id "
    "JOIN lexicons l ON l.id = w.lexicon_id "
    "JOIN users u ON u.id = l.user_id "
    "WHERE u.user_id = %s AND l.lexicon_id = %s "
    "AND (%s::timestamptz IS NULL OR r.response_time >= %s) "
    "AND (%s::text[] IS NULL OR w.word = ANY(%s))"
)

_DELETE_RECORDS: LiteralString = (
    "DELETE FROM lexicon_records r "
    "USING lexicon_words w, lexicons l, users u "
    "WHERE r.word_id = w.id AND w.lexicon_id = l.id AND l.user_id = u.id "
    "AND u.user_id = %s AND l.lexicon_id = %s "
    "AND (%s::timestamptz IS NULL OR r.response_time >= %s) "
    "AND (%s::text[] IS NULL OR w.word = ANY(%s))"
)

# Reset each word's cached state to its latest surviving record (the same rule
# `save_lexicon` applies on every write). Parameter order: user, lexicon.
_REBUILD_CACHE: LiteralString = (
    "UPDATE lexicon_words w "
    "SET response = latest.response, last_seen = latest.response_time, "
    "to_skip = (latest.extra->>'sk')::boolean "
    "FROM (SELECT DISTINCT ON (r.word_id) "
    "r.word_id, r.response, r.response_time, r.extra "
    "FROM lexicon_records r "
    "JOIN lexicon_words w2 ON w2.id = r.word_id "
    "JOIN lexicons l ON l.id = w2.lexicon_id "
    "JOIN users u ON u.id = l.user_id "
    "WHERE u.user_id = %s AND l.lexicon_id = %s "
    "ORDER BY r.word_id, r.response_time DESC, r.id DESC) latest "
    "WHERE w.id = latest.word_id"
)

# Drop words that have no records left. Parameter order: user, lexicon.
_DROP_EMPTY_WORDS: LiteralString = (
    "DELETE FROM lexicon_words w USING lexicons l, users u "
    "WHERE w.lexicon_id = l.id AND l.user_id = u.id "
    "AND u.user_id = %s AND l.lexicon_id = %s "
    "AND NOT EXISTS (SELECT 1 FROM lexicon_records r WHERE r.word_id = w.id)"
)


def _parse_after(value: str) -> datetime:
    """Parse an ISO date/time argument, assuming UTC if no zone is given."""

    moment: datetime = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


def main() -> None:
    """Preview or delete wrong lexicon records, fixing the derived cache."""

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--user", required=True, help="user login, e.g. `enzet`"
    )
    parser.add_argument(
        "--lexicon", required=True, help="lexicon identifier, e.g. `fr`"
    )
    parser.add_argument(
        "--after",
        type=_parse_after,
        help="delete records on or after this ISO date/time (UTC if no zone)",
    )
    parser.add_argument(
        "--words", nargs="+", help="restrict deletion to these words"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually delete; without it the script only previews",
    )
    arguments: argparse.Namespace = parser.parse_args()

    if arguments.after is None and not arguments.words:
        parser.error("provide --after and/or --words to choose what to delete")

    if postgres.get_lexicon_config(arguments.user, arguments.lexicon) is None:
        message: str = (
            f"No lexicon `{arguments.lexicon}` for user `{arguments.user}`."
        )
        raise SystemExit(message)

    # `after`/`words` appear twice each: once for the NULL check, once for the
    # comparison (see `_RECORD_PREDICATE`).
    predicate_params: list[object] = [
        arguments.user,
        arguments.lexicon,
        arguments.after,
        arguments.after,
        arguments.words,
        arguments.words,
    ]
    scope_params: tuple[str, str] = (arguments.user, arguments.lexicon)

    with postgres.db_connection() as connection, connection.cursor() as cursor:
        cursor.execute(_COUNT_RECORDS, predicate_params)
        if not (row := cursor.fetchone()):
            return
        record_count, word_count = row
        logger.info(
            "Records to delete: %d (across %d words).", record_count, word_count
        )
        if record_count == 0:
            logger.info("Nothing matches; nothing to do.")
            return
        if not arguments.apply:
            logger.info("Dry run. Re-run with --apply to delete.")
            return

        cursor.execute(_DELETE_RECORDS, predicate_params)
        deleted: int = cursor.rowcount
        cursor.execute(_REBUILD_CACHE, scope_params)
        cursor.execute(_DROP_EMPTY_WORDS, scope_params)
        dropped: int = cursor.rowcount

    logger.info(
        "Done: deleted %d records, dropped %d now-empty words.",
        deleted,
        dropped,
    )


if __name__ == "__main__":
    main()
