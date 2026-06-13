"""Create a user in the PostgreSQL database, or list existing users.

A user is identified by a stable string login (`user_id`) and has a display
name. Email and password are optional and may be added later by the API; the
CLI and tests do not need them.

Usage:

    python scripts/create_user.py --user alice --name "Alice"
    python scripts/create_user.py --list

The database connection string is taken from the `EMMIO_DATABASE_URL` or
`DATABASE_URL` environment variable (default: `postgresql:///emmio`).
"""

import argparse
import logging

from emmio import postgres

logger: logging.Logger = logging.getLogger(__name__)


def main() -> None:
    """Create a user or list existing users."""

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=__doc__
    )
    parser.add_argument("--user", help="user login, e.g. `alice`")
    parser.add_argument("--name", help="display name; defaults to the login")
    parser.add_argument(
        "--list",
        action="store_true",
        help="list existing users instead of creating one",
    )
    arguments: argparse.Namespace = parser.parse_args()

    if arguments.list:
        for existing_id, existing_name in postgres.list_users():
            logger.info("%s (%s)", existing_id, existing_name)
        return

    if not arguments.user:
        parser.error("either --user or --list is required")

    name: str = arguments.name or arguments.user
    if postgres.user_exists(arguments.user):
        logger.info("User `%s` already exists.", arguments.user)
        return

    postgres.ensure_user(arguments.user, name)
    logger.info("User `%s` (%s) created.", arguments.user, name)


if __name__ == "__main__":
    main()
