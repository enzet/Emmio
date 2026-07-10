"""Export user data from PostgreSQL back to JSON files.

Writes learning and lexicon data in the same JSON format that was used for
file-based storage before the PostgreSQL migration. Intended for backups and
for tracking changes with Git: run the export, then review `git diff` in the
data repository.

Usage:

    python scripts/export_json.py --user enzet --output /path/to/repo

Artifacts are read from PostgreSQL (the source of truth), so lexicons and
courses created through the web are included too. The local `config.json`, if
present, is used only to keep historical file names; artifacts without one are
written as `<id>.json`.

The output directory gets `learn/` and `lexicon/` subdirectories with one
JSON file per artifact, plus a `config.json` snapshot of the configurations
in the historical format. The application no longer reads `learn`/`lexicon`
sections from that file (they live in PostgreSQL); it is written so that
configuration changes show up in the Git history alongside the records.
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from emmio import postgres
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

    user_row: tuple[str, str, str | None] | None = postgres.get_user(
        arguments.user
    )
    if user_row is None:
        message: str = f"User `{arguments.user}` not found in the database."
        raise SystemExit(message)

    # The local `config.json` (if present) only maps artifact ids to their
    # historical file names, so exported files keep stable names and Git diffs
    # stay clean. The artifacts themselves come from PostgreSQL, which is the
    # source of truth and also holds artifacts created through the web that were
    # never written to `config.json`.
    user_path: Path = arguments.data_dir / "users" / arguments.user
    config_path: Path = user_path / "config.json"
    if config_path.exists():
        with config_path.open(encoding="utf-8") as config_file:
            user_config: dict[str, Any] = json.load(config_file)
    else:
        user_config = {}

    def file_name_for(section: str, artifact_id: str) -> str:
        """Historical file name for an artifact id, or `<id>.json`."""
        entry: dict = user_config.get(section, {}).get(artifact_id, {})
        name: str = entry.get("file_name", f"{artifact_id}.json")
        # Always export as JSON, even if the original file used YAML.
        return str(Path(name).with_suffix(".json"))

    learn_path: Path = arguments.output / "learn"
    lexicon_path: Path = arguments.output / "lexicon"
    learn_path.mkdir(parents=True, exist_ok=True)
    lexicon_path.mkdir(parents=True, exist_ok=True)

    learn_configs: dict[str, dict] = postgres.get_learn_configs(arguments.user)
    lexicon_configs: dict[str, dict] = postgres.get_lexicon_configs(
        arguments.user
    )

    for course_id, config in learn_configs.items():
        learning: Learning = Learning.from_config(
            learn_path, LearnConfig(**config), course_id, arguments.user
        )
        (learn_path / file_name_for("learn", course_id)).write_text(
            learning.dump_json() + "\n", encoding="utf-8"
        )
        logger.info(
            "Learning `%s`: %d records.",
            course_id,
            len(learning.process.records),
        )

    for lexicon_id, config in lexicon_configs.items():
        lexicon: Lexicon = Lexicon.from_config(
            lexicon_path, lexicon_id, LexiconConfig(**config), arguments.user
        )
        (lexicon_path / file_name_for("lexicon", lexicon_id)).write_text(
            lexicon.dump_json() + "\n", encoding="utf-8"
        )
        logger.info(
            "Lexicon `%s`: %d records.", lexicon_id, len(lexicon.log.records)
        )

    # Snapshot the configurations into `config.json` in the historical format,
    # so they are versioned in Git next to the records. Keys the database does
    # not own (`name`, `read`, `listen`, ...) are carried over from the local
    # config; the `learn`/`lexicon` sections are rebuilt from PostgreSQL, each
    # entry pointing at the file this export wrote.
    snapshot: dict[str, Any] = (
        dict(user_config) if user_config else {"listen": {}}
    )
    snapshot["name"] = user_row[1] or user_config.get("name", arguments.user)
    snapshot["learn"] = {
        course_id: {"file_name": file_name_for("learn", course_id), **config}
        for course_id, config in learn_configs.items()
    }
    snapshot["lexicon"] = {
        lexicon_id: {
            "file_name": file_name_for("lexicon", lexicon_id),
            **config,
        }
        for lexicon_id, config in lexicon_configs.items()
    }
    (arguments.output / "config.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    logger.info(
        "Configuration snapshot: %d courses, %d lexicons.",
        len(learn_configs),
        len(lexicon_configs),
    )

    logger.info("Export finished: `%s`.", arguments.output)


if __name__ == "__main__":
    main()
