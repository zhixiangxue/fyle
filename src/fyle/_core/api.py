"""Top-level API — ``fyle.open`` / ``fyle.read`` / ``fyle.readers``."""
from __future__ import annotations

from pathlib import Path
from typing import IO, Any, Optional, Union
from urllib.parse import urlparse

from . import fetcher, registry, sniffer
from .document import Document

Src = Union[str, Path, bytes, bytearray, IO[Any]]

_readers_loaded: bool = False


def _ensure_readers() -> None:
    """Trigger reader registration and startup validation on first use."""
    global _readers_loaded
    if _readers_loaded:
        return
    # Imported lazily to avoid a circular import during ``fyle`` package init.
    from .. import _readers  # noqa: F401

    registry.validate()
    _readers_loaded = True


def _normalize(src: Src) -> tuple[bytes, Optional[str], Optional[str], Optional[str]]:
    """Normalise ``src`` to ``(bytes, source_name, content_type, source_path)``.

    Dispatcher responsibility: every reader receives plain ``bytes``, so
    individual readers never have to handle polymorphic inputs.

    ``source_path`` is the absolute filesystem path of a local file source,
    or ``None`` for URL / bytes / file-like inputs. Most readers ignore it;
    the archive reader needs it to decide where to extract.
    """
    # URL.
    if isinstance(src, str) and (src.startswith("http://") or src.startswith("https://")):
        data, ct = fetcher.fetch(src)
        parsed_path = urlparse(src).path
        name = parsed_path.rsplit("/", 1)[-1] if parsed_path else None
        return data, (name or None), ct, None

    # Local filesystem path.
    if isinstance(src, (str, Path)):
        p = Path(src)
        try:
            resolved = str(p.resolve())
        except OSError:
            resolved = str(p)
        return p.read_bytes(), p.name, None, resolved

    # bytes / bytearray.
    if isinstance(src, (bytes, bytearray)):
        return bytes(src), None, None, None

    # File-like object.
    if hasattr(src, "read"):
        try:
            seekable = bool(src.seekable()) if hasattr(src, "seekable") else False
        except Exception:
            seekable = False
        if seekable:
            try:
                src.seek(0)
            except Exception:
                pass
        data = src.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        raw_name = getattr(src, "name", None)
        if isinstance(raw_name, bytes):
            try:
                raw_name = raw_name.decode("utf-8", errors="ignore")
            except Exception:
                raw_name = None
        if isinstance(raw_name, str):
            name = Path(raw_name).name
            # A file-like object whose ``name`` is a real filesystem path
            # lets us surface an absolute ``source_path`` too.
            try:
                candidate = Path(raw_name)
                source_path = str(candidate.resolve()) if candidate.exists() else None
            except OSError:
                source_path = None
        else:
            name = None
            source_path = None
        return bytes(data), name, None, source_path

    raise TypeError(f"Unsupported src type: {type(src).__name__}")


def open(src: Src, *, reader: Optional[str] = None) -> Document:
    """Open a document and return a ``Document``.

    ``src`` accepts: a local path (``str`` / ``Path``), ``bytes``, a file-like
    object, or an ``http(s)://`` URL. Pass ``reader=<name>`` to force a
    specific reader (see ``fyle.readers()`` for the list of available names).
    """
    _ensure_readers()
    data, source_name, content_type, source_path = _normalize(src)
    fmt = sniffer.detect(data, source_name=source_name, content_type=content_type)
    reader_cls = registry.resolve(fmt, reader)
    doc = reader_cls().read(data, source_name=source_name, source_path=source_path)
    # Fill in the final meta fields that only the dispatcher can know.
    doc.meta.reader = reader_cls.name
    if not doc.meta.format:
        doc.meta.format = fmt
    if not doc.meta.size:
        doc.meta.size = len(data)
    # Fine-grained subtype. ``format`` is the reader family (e.g. ``image``,
    # ``text``); ``ext`` pins down the concrete subtype (``png`` vs ``jpeg``,
    # ``py`` vs ``json``). Filled centrally so every reader gets it for free.
    if doc.meta.ext is None and source_name:
        suffix = Path(source_name).suffix.lower().lstrip(".")
        doc.meta.ext = suffix or None
    # Normalise ``title`` to a filename stem. Two independent sources can
    # leave ``title`` already ending in ``.ext``:
    #   1. A reader falls back to ``source_name`` (full filename) when the
    #      document has no embedded title field.
    #   2. Some producers embed a title string that itself includes the
    #      filename extension (common for PDFs generated from ``save as``).
    # Either way, pairing such a ``title`` with the separately-stored
    # ``ext`` would double the suffix in the file-level header
    # (``report.pdf.pdf``). Strip the redundant suffix centrally, case-
    # insensitively, while preserving the title's original casing.
    if doc.meta.title and doc.meta.ext:
        suffix_with_dot = "." + doc.meta.ext.lower()
        if doc.meta.title.lower().endswith(suffix_with_dot):
            doc.meta.title = doc.meta.title[: -len(suffix_with_dot)] or doc.meta.title
    # Surface the original URL for remote sources so the LLM-ready header
    # can tell the model *where* the file came from — the domain alone
    # (arxiv.org / github.com / a vendor's docs site) is a strong
    # semantic signal. Local filesystem paths are intentionally not
    # surfaced here (privacy: avoids leaking ``/Users/<user>/...`` into
    # any payload the user later shares, logs, or forwards to a hosted
    # model API). bytes / file-like inputs have no URL to surface.
    if isinstance(src, str) and (
        src.startswith("http://") or src.startswith("https://")
    ):
        doc.meta.source = src
    return doc


def read(src: Src, *, reader: Optional[str] = None) -> str:
    """Sugar: equivalent to ``str(open(src, reader=reader))``.

    Returns the LLM-ready payload (file-level header + Markdown content),
    which is what most callers of a one-liner convenience actually want.
    For the raw content without the header, use ``open(src).text``.
    """
    return str(open(src, reader=reader))


def readers() -> dict[str, list[str]]:
    """Return the readers available in the current environment.

    The default reader for each format is suffixed with ``*``. Example:
    ``{"pdf": ["pymupdf4llm*", "pdfplumber", "pypdf"], ...}``.
    """
    _ensure_readers()
    return registry.list_all()
