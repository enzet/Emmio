"""Create a user in the PostgreSQL database, or list existing users.

A user is identified by a stable string login (`user_id`) and has a display
name. With `--credentials`, the script prompts for an email and password (not
echoed) and sets them, so the user can sign in via the API — including a
CLI-only user that had none.

Usage:

    python scripts/create_user.py --user alice --name "Alice"
    python scripts/create_user.py --user enzet --credentials
    python scripts/create_user.py --list

The database connection string is taken from the `EMMIO_DATABASE_URL` or
`DATABASE_URL` environment variable (default: `postgresql:///emmio`).
"""

import argparse
import getpass
import logging

from emmio import postgres
from emmio.api import auth

logger: logging.Logger = logging.getLogger(__name__)


def _prompt_credentials() -> tuple[str, str]:
    """Prompt for a login email and password (entered twice, not echoed)."""

    email: str = input("Email: ").strip()
    password: str = getpass.getpass("Password: ")
    if password != getpass.getpass("Password (again): "):
        message: str = "Passwords do not match."
        raise SystemExit(message)
    return email, password


def main() -> None:
    """Create a user, set credentials, or list existing users."""

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=__doc__
    )
    parser.add_argument("--user", help="user login, e.g. `alice`")
    parser.add_argument("--name", help="display name; defaults to the login")
    parser.add_argument(
        "--credentials",
        action="store_true",
        help="prompt for an email and password and set them",
    )
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

    # Create the user if it does not exist yet.
    if not postgres.user_exists(arguments.user):
        postgres.ensure_user(arguments.user, name)
        logger.info("User `%s` (%s) created.", arguments.user, name)
    elif not arguments.credentials:
        logger.info("User `%s` already exists.", arguments.user)

    # Set login credentials if requested.
    if arguments.credentials:
        email, password = _prompt_credentials()
        postgres.set_credentials(
            arguments.user, email, auth.hash_password(password)
        )
        logger.info(
            "Credentials set for `%s` (login email: %s).", arguments.user, email
        )


if __name__ == "__main__":
    main()
