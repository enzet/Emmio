"""One-time migration of leftover `config.json` sections to PostgreSQL.

Learning and lexicon configurations were migrated by `migrate_local.py`; this
script moves what remained in the per-user `config.json`: the sections
without dedicated tables (`listen`, plus historical sections such as `read`)
go into the `config` JSONB column of the `users` table. After it, the
application reads no user configuration from files.

Usage:

    python scripts/migrate_user_config.py --user enzet \
        --data-dir /path/to/data

The `id`, `name`, `learn`, and `lexicon` keys are skipped: the first two are
columns of the `users` table, the last two live in their own tables.
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from emmio import postgres

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

logger: logging.Logger = logging.getLogger(__name__)

MIGRATED_ELSEWHERE: set[str] = {"id", "name", "learn", "lexicon"}
"""Sections already stored in dedicated columns or tables."""


def main() -> None:
    """Run the migration."""

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
    arguments: argparse.Namespace = parser.parse_args()

    if postgres.get_user(arguments.user) is None:
        message: str = f"User `{arguments.user}` not found in the database."
        raise SystemExit(message)

    config_path: Path = (
        arguments.data_dir / "users" / arguments.user / "config.json"
    )
    with config_path.open(encoding="utf-8") as config_file:
        user_config: dict[str, Any] = json.load(config_file)

    remaining: dict[str, Any] = {
        key: value
        for key, value in user_config.items()
        if key not in MIGRATED_ELSEWHERE
    }
    postgres.store_user_config(arguments.user, remaining)
    logger.info(
        "Stored sections %s for `%s`.",
        ", ".join(f"`{key}`" for key in remaining) or "(none)",
        arguments.user,
    )


if __name__ == "__main__":
    main()
