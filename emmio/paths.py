"""Default Emmio paths."""

from pathlib import Path

EMMIO_DEFAULT_DIRECTORY: str = ".emmio"


def get_default_output_directory() -> Path:
    """Get the default output directory, creating it if it doesn't exist."""

    (default_output_directory := Path("out")).mkdir(parents=True, exist_ok=True)
    return default_output_directory
