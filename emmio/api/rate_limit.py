"""In-process rate limiting for abuse-prone endpoints.

Deliberately dependency-free (no `slowapi`/Redis): a fixed-window counter
keyed by client IP, held in a plain dict behind a lock. This is enough for a
single-process deployment -- the `Dockerfile` runs one `uvicorn` process, no
`--workers` -- but does *not* share state across multiple processes/replicas;
revisit with a shared store if this ever runs behind more than one process.
"""

import time
from collections.abc import Callable
from threading import Lock

from fastapi import HTTPException, Request, status


class RateLimiter:
    """Fixed-window request limiter, keyed by an arbitrary string (IP)."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        """Allow at most `max_requests` per `window_seconds`, per key.

        :param max_requests: requests allowed within one window
        :param window_seconds: window length, in seconds
        """
        self._max_requests: int = max_requests
        self._window_seconds: float = window_seconds
        # No type annotation: `threading.Lock` is a factory, not a type, so
        # beartype cannot check it (see `emmio/sentence/tatoeba.py`).
        self._lock = Lock()
        # Key -> (window start, count so far in that window).
        self._hits: dict[str, tuple[float, int]] = {}

    def check(self, key: str) -> None:
        """Count one request for `key`; raise 429 if it is over budget.

        :raises HTTPException: 429, if `key` has exceeded its budget for the
            current window
        """
        now: float = time.monotonic()
        with self._lock:
            window_start, count = self._hits.get(key, (now, 0))
            if now - window_start >= self._window_seconds:
                window_start, count = now, 0
            count += 1
            self._hits[key] = (window_start, count)
            if count > self._max_requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Try again later.",
                )

    def clear(self) -> None:
        """Drop all tracked counters."""
        with self._lock:
            self._hits.clear()

    def as_dependency(self) -> Callable[[Request], None]:
        """Build a FastAPI dependency that rate-limits by client IP.

        Relies on `Request.client.host` already being the real client
        address, not a reverse proxy's -- see the `Dockerfile`'s
        `--proxy-headers` flag and `docker-compose.yml`'s network layout
        (the `api` service has no published port, so only the trusted Caddy
        container can reach it, which is what makes trusting forwarded
        headers unconditionally safe here).
        """

        def _check(request: Request) -> None:
            client_host: str = (
                request.client.host if request.client else "unknown"
            )
            self.check(client_host)

        return _check
