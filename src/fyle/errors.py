"""Public exception types.

Fatal vs partial failure dichotomy:
- Fatal: ``ParseError`` / ``UnsupportedFormatError`` / ``ReaderNotFoundError`` /
  ``DownloadError``. These are raised from ``fyle.open`` / ``fyle.read``.
- Partial: recorded in ``doc.meta.warnings``; no exception is raised.
"""
from __future__ import annotations


class UnsupportedFormatError(Exception):
    """Raised when format sniffing fails on all three paths.

    Extension, magic bytes, and HTTP Content-Type all produced no match.
    """


class ParseError(Exception):
    """Fatal parse failure: corrupted file, reader/format mismatch, etc.

    fyle does not auto-fallback to another reader; the caller must handle it.
    """


class ReaderNotFoundError(Exception):
    """Reader name is unknown, or the reader does not support the target format."""


class DownloadError(Exception):
    """URL fetch failed: network error, timeout, or response exceeds max_bytes.

    Wraps the underlying ``httpx`` exception.
    """


class NotImplementedReaderError(NotImplementedError):
    """The format is recognised, but no real reader implementation ships yet.

    Used by placeholder readers that reserve a format slot (e.g. audio, video)
    so that ``fyle.open`` can produce a clear, format-specific error instead
    of falling through to ``UnsupportedFormatError``.
    """
