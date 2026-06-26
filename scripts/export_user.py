"""Export all data Emmio holds about a user as a single ZIP archive.

This is the "download my data" / data-portability export (GDPR Art. 15 and
20): a self-describing archive with the user's account profile and every
learning, lexicon, and listening artifact, in a structured, machine-readable
form (JSON).

Unlike `export_json.py` (a Git-friendly backup of learning and lexicon data),
this script aims for completeness: it also includes the account profile (name,
email, sign-up date) and the on-disk listening data and configuration. The
password hash is never exported. See `emmio.user.export` for the archive layout.

Usage:

    python scripts/export_user.py --user enzet --output enzet-emmio-data.zip
"""

import argparse
import logging
from pathlib import Path

from emmio.user.export import UnknownUserError, build_archive

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
        help="path of the ZIP archive to write "
        "(default: `<user>-emmio-data.zip` in the current directory)",
    )
    arguments: argparse.Namespace = parser.parse_args()

    output: Path = arguments.output or Path(f"{arguments.user}-emmio-data.zip")
    try:
        archive: Path = build_archive(
            arguments.user, arguments.data_dir, output
        )
    except UnknownUserError as error:
        parser.error(str(error))

    logger.info("Export finished: `%s`.", archive)


if __name__ == "__main__":
    main()
