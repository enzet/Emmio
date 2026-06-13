"""Export user data from PostgreSQL back to JSON files.

Writes learning and lexicon data in the same JSON format that was used for
file-based storage before the PostgreSQL migration. Intended for backups and
for tracking changes with Git: run the export, then review `git diff` in the
data repository.

Usage:

    python scripts/export_json.py --user enzet --output /path/to/repo

The output directory gets `learn/` and `lexicon/` subdirectories with one
JSON file per artifact, named after `file_name` in the user configuration.
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from emmio.learn.config import LearnConfig
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
        "--data-dir",
        type=Path,
        default=Path.home() / ".emmio",
        help="path to Emmio data directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="directory to write JSON files to",
    )
    arguments: argparse.Namespace = parser.parse_args()

    user_path: Path = arguments.data_dir / "users" / arguments.user
    with (user_path / "config.json").open(encoding="utf-8") as config_file:
        user_config: dict[str, Any] = json.load(config_file)

    learn_path: Path = arguments.output / "learn"
    lexicon_path: Path = arguments.output / "lexicon"
    learn_path.mkdir(parents=True, exist_ok=True)
    lexicon_path.mkdir(parents=True, exist_ok=True)

    for course_id, config in user_config.get("learn", {}).items():
        learning: Learning = Learning.from_config(
            learn_path, LearnConfig(**config), course_id
        )
        # Export under the configured file name, but always as JSON, even if
        # the original file was in the old YAML format.
        file_name: str = str(Path(config["file_name"]).with_suffix(".json"))
        (learn_path / file_name).write_text(
            learning.dump_json() + "\n", encoding="utf-8"
        )
        logger.info(
            "Learning `%s`: %d records.",
            course_id,
            len(learning.process.records),
        )

    for lexicon_id, config in user_config.get("lexicon", {}).items():
        lexicon: Lexicon = Lexicon.from_config(
            lexicon_path, lexicon_id, LexiconConfig(**config)
        )
        (lexicon_path / config["file_name"]).write_text(
            lexicon.dump_json() + "\n", encoding="utf-8"
        )
        logger.info(
            "Lexicon `%s`: %d records.", lexicon_id, len(lexicon.log.records)
        )

    logger.info("Export finished: `%s`.", arguments.output)


if __name__ == "__main__":
    main()
