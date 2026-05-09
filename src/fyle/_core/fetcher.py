"""URL fetcher — built on ``httpx`` with timeout and max_bytes safety limits.

Defaults: ``timeout=30s`` and ``max_bytes=100MB``. Override via environment
variables ``FYLE_HTTP_TIMEOUT`` and ``FYLE_HTTP_MAX_BYTES``.
"""
from __future__ import annotations

import os
from typing import Optional

from ..errors import DownloadError

DEFAULT_TIMEOUT: float = 30.0
DEFAULT_MAX_BYTES: int = 100 * 1024 * 1024  # 100 MB


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    if not v:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def fetch(url: str) -> tuple[bytes, Optional[str]]:
    """Fetch ``url`` and return ``(bytes, content_type)``.

    Timeouts, network errors, and responses exceeding ``max_bytes`` are all
    raised as ``fyle.DownloadError`` (wrapping the underlying ``httpx`` error).
    """
    try:
        import httpx
    except ImportError as e:  # pragma: no cover
        raise DownloadError("httpx is required for URL fetching: pip install httpx") from e

    timeout = _env_float("FYLE_HTTP_TIMEOUT", DEFAULT_TIMEOUT)
    max_bytes = _env_int("FYLE_HTTP_MAX_BYTES", DEFAULT_MAX_BYTES)

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("content-type")
                buf = bytearray()
                for chunk in resp.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise DownloadError(
                            f"Response exceeds max_bytes={max_bytes}. "
                            f"Override via FYLE_HTTP_MAX_BYTES env var."
                        )
                return bytes(buf), content_type
    except DownloadError:
        raise
    except httpx.HTTPError as e:
        raise DownloadError(f"Failed to fetch {url!r}: {e}") from e
