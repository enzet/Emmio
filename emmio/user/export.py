"""Build a complete export of all data Emmio holds about a user.

This is the engine behind the "download my data" / data-portability export
(GDPR Art. 15 and 20), shared by the `scripts/export_user.py` command-line tool
and the `/api/v1/me/export` API endpoint. It produces a single self-describing
ZIP archive with the user's account profile and every learning, lexicon, and
listening artifact, in a structured, machine-readable form (JSON).

The password hash is never exported.
"""

import json
import logging
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from emmio import postgres
from emmio.learn.config import LearnConfig
from emmio.learn.core import Learning
from emmio.lexicon.config import LexiconConfig
from emmio.lexicon.core import Lexicon

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

logger: logging.Logger = logging.getLogger(__name__)

README_TEXT: str = """\
Emmio personal data export
==========================

This archive contains all the data Emmio holds about the user `{user_id}`,
exported on request.

  profile.json       Account information: login, display name, email, and the
                     date the account was created. The password is not
                     included: only a one-way hash is ever stored, and it is of
                     no use to you.
  config.json        Your Emmio configuration (preferences), if present.
  learn/<id>.json    One file per learning course, with every answer you gave
                     and every study session.
  lexicon/<id>.json  One file per lexicon, with every word you judged known or
                     unknown and every checking session.
  listen/            Your listening data, if present, copied unchanged.

All data files are JSON (UTF-8). Times are in UTC.
"""


class UnknownUserError(Exception):
    """Raised when there is no account to export for the given login."""


def build_archive(user_id: str, data_dir: Path, output: Path) -> Path:
    """Build a ZIP archive of all data Emmio holds about a user.

    :param user_id: login of the user to export, e.g. `john`
    :param data_dir: Emmio data directory (holds `users/<id>/` with the on-disk
        configuration and listening data)
    :param output: path of the ZIP archive to create (the `.zip` suffix is
        added if missing)
    :return: the path of the created archive
    :raises UnknownUserError: if the user does not exist in the database
    """
    profile: dict[str, object] | None = postgres.get_account(user_id)
    if profile is None:
        message: str = f"Unknown user `{user_id}`."
        raise UnknownUserError(message)

    user_path: Path = data_dir / "users" / user_id

    with TemporaryDirectory() as temporary:
        root: Path = Path(temporary)

        # Account profile.
        (root / "profile.json").write_text(
            json.dumps(profile, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )

        # User configuration (preferences), if present on disk.
        config_path: Path = user_path / "config.json"
        if config_path.exists():
            shutil.copyfile(config_path, root / "config.json")

        # Learning courses, from the database.
        learn_path: Path = root / "learn"
        learn_path.mkdir()
        for course_id, config in postgres.get_learn_configs(user_id).items():
            learning: Learning = Learning.from_config(
                learn_path, LearnConfig(**config), course_id, user_id
            )
            (learn_path / f"{course_id}.json").write_text(
                learning.dump_json() + "\n", encoding="utf-8"
            )
            logger.info(
                "Learning `%s`: %d records.",
                course_id,
                len(learning.process.records),
            )

        # Lexicons, from the database.
        lexicon_path: Path = root / "lexicon"
        lexicon_path.mkdir()
        for lexicon_id, config in postgres.get_lexicon_configs(user_id).items():
            lexicon: Lexicon = Lexicon.from_config(
                lexicon_path, lexicon_id, LexiconConfig(**config), user_id
            )
            (lexicon_path / f"{lexicon_id}.json").write_text(
                lexicon.dump_json() + "\n", encoding="utf-8"
            )
            logger.info(
                "Lexicon `%s`: %d records.",
                lexicon_id,
                len(lexicon.log.records),
            )

        # Listening data, copied as-is from disk, if present.
        listen_path: Path = user_path / "listen"
        if listen_path.is_dir() and any(listen_path.iterdir()):
            shutil.copytree(listen_path, root / "listen")

        (root / "README.txt").write_text(
            README_TEXT.format(user_id=user_id), encoding="utf-8"
        )

        archive: str = shutil.make_archive(
            str(output.with_suffix("")), "zip", root
        )

    return Path(archive)
