# Runs the Emmio API + same-origin web client (`uvicorn emmio.api.app:app`).
# Does NOT bundle the shared data directory (frequency lists, dictionaries,
# sentences, audio — see research/app.md "Provision shared data"): mount it
# at the path EMMIO_DATA_DIR points to, or, for a curated-lexicon-only
# deployment, bake in just the small curated export instead.

FROM python:3.12-slim

# ffmpeg backs emmio/audio/transcode.py (Ogg Vorbis -> MP3 for Safari/iOS
# pronunciation playback); transcoding falls back to the original file when
# ffmpeg is missing, so this is wanted, not strictly required. The `mpv`
# Python package (a core, non-`api`-extra dependency, used by the CLI's
# audio playback and unrelated to serving the API) already tolerates a
# missing libmpv at import time, so it is deliberately not installed here.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY emmio/ emmio/
COPY web/ web/
COPY doc/ doc/
COPY data/ data/

# Editable install: mirrors the project's own documented `pip install
# -e .[api]` (see README.md "Other Interfaces"), which sidesteps relying on
# `[tool.setuptools] packages = ["emmio"]` (a non-recursive list) to also
# correctly bundle every subpackage (`emmio.api`, `emmio.lexicon`, ...) into
# a built wheel -- editable mode just puts the already-copied source tree
# on `sys.path` instead.
RUN pip install --no-cache-dir -e .[api]

RUN useradd --create-home --uid 1000 emmio && chown -R emmio:emmio /app
USER emmio

EXPOSE 8000

# $PORT is honored so this also runs unmodified on platforms that assign it
# (Railway, Render, ...); Fly.io instead maps a fixed internal port in
# fly.toml, so 8000 is the fallback either way.
CMD ["sh", "-c", "uvicorn emmio.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
