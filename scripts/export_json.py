"""Export user data from PostgreSQL back to JSON files.

Writes learning and lexicon data in the same JSON format that was used for
file-based storage before the PostgreSQL migration. Intended for backups and
for tracking changes with Git: run the export, then review `git diff` in the
data repository.

Usage:

    python scripts/export_json.py --user enzet --output /path/to/repo

Everything is read from PostgreSQL (the single source of truth), so lexicons
and courses created through the web are included too; nothing is read from
the data repository itself.

The output directory gets `learn/` and `lexicon/` subdirectories with one
`<id>.json` file per artifact, plus a `config.json` snapshot of the
configurations in the historical format. The application never reads that
file; it is written so that configuration changes show up in the Git history
alongside the records.
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from emmio import postgres
from emmio.learn.config import LearningConfig
from emmio.learn.core import Learning
from emmio.lexicon.config import LexiconConfig
from emmio.lexicon.core import Lexicon

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

logger: logging.Logger = logging.getLogger(__name__)


def main() -> None:
    """Run the export."""

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=__doc__
    )
    parser.add_argument("--user", required=True, help="user identifier")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="directory to write JSON files to",
    )
    arguments: argparse.Namespace = parser.parse_args()

    user_row: tuple[str, str, str | None] | None = postgres.get_user(
        arguments.user
    )
    if user_row is None:
        message: str = f"User `{arguments.user}` not found in the database."
        raise SystemExit(message)

    learn_path: Path = arguments.output / "learn"
    lexicon_path: Path = arguments.output / "lexicon"
    learn_path.mkdir(parents=True, exist_ok=True)
    lexicon_path.mkdir(parents=True, exist_ok=True)

    learn_configs: dict[str, dict] = postgres.get_learning_configs(
        arguments.user
    )
    lexicon_configs: dict[str, dict] = postgres.get_lexicon_configs(
        arguments.user
    )

    for learning_id, config in learn_configs.items():
        learning: Learning = Learning.from_config(
            learn_path, LearningConfig(**config), learning_id, arguments.user
        )
        (learn_path / f"{learning_id}.json").write_text(
            learning.dump_json() + "\n", encoding="utf-8"
        )
        logger.info(
            "Learning `%s`: %d records.",
            learning_id,
            len(learning.process.records),
        )

    for lexicon_id, config in lexicon_configs.items():
        lexicon: Lexicon = Lexicon.from_config(
            lexicon_path, lexicon_id, LexiconConfig(**config), arguments.user
        )
        (lexicon_path / f"{lexicon_id}.json").write_text(
            lexicon.dump_json() + "\n", encoding="utf-8"
        )
        logger.info(
            "Lexicon `%s`: %d records.", lexicon_id, len(lexicon.log.records)
        )

    # Snapshot the configurations into `config.json` in the historical format,
    # so they are versioned in Git next to the records. The `learn`/`lexicon`
    # sections point at the files this export wrote; sections without
    # dedicated tables (`listen`, historical `read`) come from the user's
    # `config` column.
    snapshot: dict[str, Any] = {
        "name": user_row[1] or arguments.user,
        "learn": {
            learning_id: {"file_name": f"{learning_id}.json", **config}
            for learning_id, config in learn_configs.items()
        },
        "lexicon": {
            lexicon_id: {"file_name": f"{lexicon_id}.json", **config}
            for lexicon_id, config in lexicon_configs.items()
        },
        **(postgres.get_user_config(arguments.user) or {}),
    }
    (arguments.output / "config.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    logger.info(
        "Configuration snapshot: %d learnings, %d lexicons.",
        len(learn_configs),
        len(lexicon_configs),
    )

    logger.info("Export finished: `%s`.", arguments.output)


if __name__ == "__main__":
    main()
