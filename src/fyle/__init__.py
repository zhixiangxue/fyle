"""fyle — open anything, get clean Markdown for LLMs.

Public surface: three entry points (``open`` / ``read`` / ``readers``), the
data model (``Document`` / ``Page`` / ``Table`` / ``Image`` / ``Meta`` /
``Chunk``), and four exception types.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from ._core.api import accepts, open, read, readers
from ._core.document import Chunk, Document, Image, Meta, Page, Table
from .errors import (
    DownloadError,
    ParseError,
    ReaderNotFoundError,
    UnsupportedFormatError,
)

__all__ = [
    # Entry points
    "open",
    "read",
    "readers",
    "accepts",
    # Data model (exposed for type hints / isinstance checks)
    "Document",
    "Page",
    "Table",
    "Image",
    "Meta",
    "Chunk",
    # Exceptions
    "UnsupportedFormatError",
    "ParseError",
    "ReaderNotFoundError",
    "DownloadError",
]

# ``pyproject.toml`` is the single source of truth for the version string.
# Read it from the installed package metadata at runtime; fall back to a
# clearly-fake value when running from an uninstalled source tree (e.g.
# ``PYTHONPATH=src python -c 'import fyle'``).
try:
    __version__ = _pkg_version("fyle")
except PackageNotFoundError:  # pragma: no cover - only hit without install
    __version__ = "0.0.0+unknown"
