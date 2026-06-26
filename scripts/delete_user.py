"""Erase all data Emmio holds about a user (right to erasure, GDPR Art. 17).

Deletes, in one database transaction, the user's account row and every learning
and lexicon artifact they own (courses, lexicons, words, records, sessions),
then removes the user's on-disk data directory (configuration and listening
data). Either everything in the database is removed or nothing is.

This is irreversible. Run `export_user.py` first if a copy is wanted.

Usage:

    python scripts/delete_user.py --user enzet            # asks to confirm
    python scripts/delete_user.py --user enzet --yes      # no prompt
    python scripts/delete_user.py --user enzet --keep-files
"""

import argparse
import logging
import shutil
from pathlib import Path

from emmio import postgres

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

logger: logging.Logger = logging.getLogger(__name__)


def main() -> None:
    """Run the erasure."""

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=__doc__
    )
    parser.add_argument("--user", required=True, help="user identifier")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / ".emmio",
        help="path to Emmio data directory",
    )
    parser.add_argument(
        "--keep-files",
        action="store_true",
        help="delete database data only, leave the on-disk directory in place",
    )
    parser.add_argument(
        "--yes", action="store_true", help="do not ask for confirmation"
    )
    arguments: argparse.Namespace = parser.parse_args()

    user_id: str = arguments.user

    account: dict[str, object] | None = postgres.get_account(user_id)
    if account is None:
        parser.error(f"Unknown user `{user_id}`.")

    if not arguments.yes:
        logger.info(
            "About to permanently erase all data for `%s` (%s). "
            "This cannot be undone.",
            user_id,
            account["email"] or "no email",
        )
        answer: str = input(f"Type the user id `{user_id}` to confirm: ")
        if answer.strip() != user_id:
            parser.error("Confirmation did not match; nothing was deleted.")

    if postgres.delete_user(user_id):
        logger.info("Deleted database data for `%s`.", user_id)
    else:
        logger.info("No database data for `%s`.", user_id)

    user_path: Path = arguments.data_dir / "users" / user_id
    if arguments.keep_files:
        logger.info("Kept on-disk directory `%s`.", user_path)
    elif user_path.exists():
        shutil.rmtree(user_path)
        logger.info("Removed on-disk directory `%s`.", user_path)

    logger.info("Erasure finished for `%s`.", user_id)


if __name__ == "__main__":
    main()
