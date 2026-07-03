"""Transcode audio into a browser-friendly format.

Safari and iOS cannot decode Ogg Vorbis, the format of most Lingua Libre and
Wikimedia Commons pronunciations. Files in an unsupported format are transcoded
to MP3 once and cached; every major browser can play MP3.
"""

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger: logging.Logger = logging.getLogger(__name__)

BROWSER_PLAYABLE_SUFFIXES: frozenset[str] = frozenset(
    {".mp3", ".m4a", ".aac", ".wav"}
)
"""Suffixes every major browser, including Safari and iOS, plays directly."""


def to_browser_playable(path: Path, cache_directory: Path) -> Path:
    """Return a browser-playable version of an audio file.

    A file already in a widely supported format (see
    `BROWSER_PLAYABLE_SUFFIXES`) is returned unchanged. Anything else — notably
    Ogg Vorbis — is transcoded to MP3 and cached under `cache_directory`, so a
    later request for the same file reuses the cached MP3. Falls back to the
    original file when ffmpeg is missing or fails, so playback still works in
    browsers that support the source format.

    :param path: path to the source audio file
    :param cache_directory: directory to store transcoded MP3 files in
    :return: path to a browser-playable file (the cached MP3, or the original)
    """
    if path.suffix.lower() in BROWSER_PLAYABLE_SUFFIXES:
        return path

    # Key the cache by source path and modification time, so replacing a source
    # file invalidates its stale transcode.
    stat = path.stat()
    key: str = hashlib.md5(f"{path}:{stat.st_mtime_ns}".encode()).hexdigest()
    target: Path = cache_directory / f"{key}.mp3"
    if target.exists():
        return target

    ffmpeg: str | None = shutil.which("ffmpeg")
    if ffmpeg is None:
        logger.warning("ffmpeg not found; serving `%s` untranscoded.", path)
        return path

    cache_directory.mkdir(parents=True, exist_ok=True)
    # Transcode to a unique temporary file and rename it into place atomically,
    # so a concurrent request never sees a half-written MP3. ffmpeg's `-y`
    # overwrites the empty file `mkstemp` created.
    descriptor, temporary_name = tempfile.mkstemp(
        dir=cache_directory, suffix=".mp3"
    )
    os.close(descriptor)
    temporary: Path = Path(temporary_name)
    try:
        subprocess.run(  # noqa: S603  # Fixed command; only a local path varies.
            [
                ffmpeg,
                "-nostdin",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(path),
                "-map_metadata",
                "-1",
                "-codec:a",
                "libmp3lame",
                "-qscale:a",
                "5",
                str(temporary),
            ],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, OSError):
        logger.exception("Failed to transcode `%s`.", path)
        temporary.unlink(missing_ok=True)
        return path
    temporary.replace(target)
    return target
