"""Data model — Document / Page / Table / Image / Meta / Chunk.

Naming rule: ``.text`` is always a Markdown string, on every level
(``doc.text``, ``page.text``, ``table.text``, ``image.text``).

The element types (``Meta`` / ``Image`` / ``Table`` / ``Page`` / ``Chunk``)
are ``pydantic.BaseModel`` subclasses, so they get runtime validation, a
proper ``.model_dump()`` / ``.model_dump_json()`` surface, and a consistent
construction contract. ``Document`` itself is intentionally a plain class
with ``__slots__`` because it caches derived views and exposes properties.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class _Element(BaseModel):
    """Shared base for every element type in the data model."""

    # Element instances are treated as value objects. ``extra="forbid"``
    # prevents silent typos at construction time; ``ser_json_bytes="base64"``
    # makes ``.model_dump_json()`` work on image payloads.
    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=False,
        ser_json_bytes="base64",
    )


class Meta(_Element):
    """Document-level metadata."""

    format: str = ""
    # Fine-grained subtype. ``format`` is the *reader family* (e.g. ``image``,
    # ``text``, ``docx``) and intentionally coarse. ``ext`` records the concrete
    # subtype so callers can distinguish ``.png`` vs ``.jpeg``, ``.py`` vs
    # ``.json``, etc., without having to re-parse ``source_name`` or the
    # ``data_url`` MIME of each image.
    # Filled by the dispatcher from the source name's suffix (lower-cased, no
    # leading dot). ``None`` when the input has no name (e.g. raw bytes with no
    # ``source_name`` and a URL whose path has no suffix).
    ext: Optional[str] = None
    # Formats without native pagination always report ``pages=1``.
    pages: int = 1
    size: int = 0
    title: Optional[str] = None
    author: Optional[str] = None
    created_at: Optional[datetime] = None
    # Original source URL for inputs fetched from ``http(s)://``. Stays
    # ``None`` for local paths, bytes, and file-like inputs: we
    # deliberately never surface local filesystem paths here to avoid
    # leaking ``/Users/<user>/...`` (or equivalent) into the LLM-ready
    # payload when it gets shared, logged, or forwarded to a hosted
    # model API. The filename in ``title`` + ``ext`` is enough.
    source: Optional[str] = None
    reader: str = ""
    warnings: list[str] = Field(default_factory=list)

    def as_dict(self) -> dict:
        """Return a JSON-friendly dict (``created_at`` as ISO-8601 string)."""
        return {
            "format": self.format,
            "ext": self.ext,
            "pages": self.pages,
            "size": self.size,
            "title": self.title,
            "author": self.author,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "source": self.source,
            "reader": self.reader,
            "warnings": list(self.warnings),
        }


class Image(_Element):
    """Image element. fyle does not perform OCR."""

    data_url: str
    # Raw image bytes. Named ``data`` rather than ``bytes`` to avoid shadowing
    # the builtin ``bytes`` type in annotations.
    data: bytes = b""
    caption: Optional[str] = None
    page: Optional[int] = None

    @property
    def text(self) -> str:
        """Return Markdown image syntax: ``![caption](data:image/...;base64,...)``.

        Keeps the ``.text`` contract consistent with ``doc.text`` /
        ``page.text`` / ``table.text``: ``.text`` is always Markdown.
        """
        alt = self.caption or ""
        return f"![{alt}]({self.data_url})"

    def save(self, path: Union[str, Path]) -> None:
        Path(path).write_bytes(self.data)


class Table(_Element):
    """Table element."""

    # Markdown table string; name aligned with ``doc.text`` / ``page.text``.
    text: str
    rows: list[list[str]] = Field(default_factory=list)
    headers: list[str] = Field(default_factory=list)
    page: Optional[int] = None


class Page(_Element):
    """Page element.

    For formats without native pagination, ``pages`` contains a single ``Page``
    with ``number=1``.

    ``name`` is an optional human-meaningful label for this page. It is used
    by formats where the page has a natural identity beyond a page number:

    - XLSX: sheet name (``ws.title``).
    - PPTX (future): slide title.

    For PDF / DOCX / HTML / plain text / Markdown / CSV it stays ``None``.
    We deliberately keep this on ``Page`` rather than introducing separate
    ``Sheet`` / ``Slide`` models: the data shape is identical and the content
    surface (``doc.text`` / ``doc.pages`` / ``doc.tables`` / ``doc.images`` /
    ``doc.meta``) must stay at exactly five attributes.
    """

    # Markdown content of this page.
    text: str
    number: int = 1
    name: Optional[str] = None
    tables: list[Table] = Field(default_factory=list)
    images: list[Image] = Field(default_factory=list)


class Chunk(_Element):
    """LLM-oriented chunk produced by ``Document.chunks()``."""

    text: str
    tokens: int
    # ``None`` for formats without native pagination.
    page_range: Optional[tuple[int, int]] = None


class Document:
    """Top-level document object returned by ``fyle.open``.

    Five content attributes (``text`` / ``pages`` / ``tables`` / ``images`` /
    ``meta``) plus three LLM helpers (``tokens`` / ``tokens_for`` / ``chunks``).
    Eight in total; the surface is frozen.
    """

    __slots__ = (
        "_pages",
        "meta",
        "_text_cache",
        "_tables_cache",
        "_images_cache",
    )

    def __init__(self, *, pages: list[Page], meta: Meta) -> None:
        self._pages = pages
        self.meta = meta
        self._text_cache: Optional[str] = None
        self._tables_cache: Optional[list[Table]] = None
        self._images_cache: Optional[list[Image]] = None

    # ------------------------------------------------------------------
    # Content attributes (5)
    # ------------------------------------------------------------------
    @property
    def text(self) -> str:
        if self._text_cache is None:
            self._text_cache = "\n\n".join(p.text for p in self._pages if p.text)
        return self._text_cache

    @property
    def pages(self) -> list[Page]:
        return self._pages

    @property
    def tables(self) -> list[Table]:
        if self._tables_cache is None:
            self._tables_cache = [t for p in self._pages for t in p.tables]
        return self._tables_cache

    @property
    def images(self) -> list[Image]:
        if self._images_cache is None:
            self._images_cache = [img for p in self._pages for img in p.images]
        return self._images_cache

    # ------------------------------------------------------------------
    # LLM helpers (3)
    # ------------------------------------------------------------------
    @property
    def tokens(self) -> int:
        from .chunking import estimate_tokens

        return estimate_tokens(self.text)

    def tokens_for(self, obj) -> int:
        from .chunking import estimate_tokens

        text = getattr(obj, "text", None)
        if text is None:
            raise TypeError(f"tokens_for expected an object with .text, got {type(obj).__name__}")
        return estimate_tokens(text)

    def chunks(self, max_tokens: int = 4000, overlap: int = 200) -> Iterator[Chunk]:
        from .chunking import chunk_document

        yield from chunk_document(self, max_tokens=max_tokens, overlap=overlap)

    # ------------------------------------------------------------------
    # Optional context manager
    # ------------------------------------------------------------------
    def __enter__(self) -> "Document":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def __repr__(self) -> str:
        return (
            f"Document(format={self.meta.format!r}, pages={len(self._pages)}, "
            f"reader={self.meta.reader!r})"
        )

    def __str__(self) -> str:
        """Return an LLM-ready payload: file-level header + ``doc.text``.

        Intended as the one-liner you hand to a model:
        ``llm.complete(str(doc))``. The header surfaces filename, format,
        and size so the model still knows what it is looking at when
        only the string is passed in (no ``doc.meta`` alongside). The
        filename in particular carries real semantic signal that
        ``doc.text`` alone would discard.

        For the raw content without the wrapper, use ``doc.text``.
        """
        header = self._file_level_header()
        if not header:
            return self.text
        return f"{header}\n\n---\n\n{self.text}"

    def _file_level_header(self) -> str:
        """Compose the outer Markdown header surfaced by ``__str__``.

        Surfaces the metadata fields that carry real semantic signal for
        an LLM reading the payload: filename, format, size, page count
        (when >1), author, creation time, and any parse warnings. The
        ``reader`` field is deliberately omitted — it's an internal
        implementation detail (which library parsed the file) with no
        value to the model; developers who need it can read
        ``doc.meta.reader`` directly.

        Content-specific metadata (audio duration, video keyframes,
        detected language, ...) belongs to the reader's own inline
        header inside ``doc.text`` and stays there.

        The core fields are rendered as a two-column ``field | value``
        Markdown table — one row per attribute. This shape stays
        compact regardless of how many fields are present and matches
        how LLMs naturally parse labeled key/value pairs. Warnings are
        rendered as a separate bullet list because they are a
        variable-length ``list[str]`` and don't fit the single-value
        row shape.
        """
        # Collect present (name, value) pairs. Every field is optional
        # so missing ones simply do not produce a row.
        fields: list[tuple[str, str]] = []
        if self.meta.title:
            # ``meta.title`` is the filename stem; ``meta.ext`` is the
            # dot-less suffix — together they reconstruct the source
            # filename. The filename is just another attribute here,
            # not a separate heading.
            filename = (
                f"{self.meta.title}.{self.meta.ext}"
                if self.meta.ext
                else self.meta.title
            )
            fields.append(("filename", filename))
        if self.meta.source:
            # Only populated for ``http(s)://`` inputs — see ``Meta.source``
            # for why local paths are excluded. The URL carries real
            # semantic signal for the LLM (arxiv.org / github.com /
            # a vendor's docs site all imply different content types).
            fields.append(("source", self.meta.source))
        if self.meta.format:
            fields.append(("format", self.meta.format))
        if self.meta.size:
            fields.append(("size", _human_size(self.meta.size)))
        if len(self._pages) > 1:
            fields.append(("pages", str(len(self._pages))))
        if self.meta.author:
            fields.append(("author", self.meta.author))
        if self.meta.created_at:
            fields.append(
                ("created", self.meta.created_at.isoformat(timespec="seconds"))
            )

        lines: list[str] = []
        if fields:
            lines.append("| field | value |")
            lines.append("| --- | --- |")
            for name, value in fields:
                lines.append(
                    f"| {_escape_table_cell(name)} | {_escape_table_cell(value)} |"
                )
        # Warnings are variable-length; give them their own bullet list
        # so they never distort the table's two-column shape.
        if self.meta.warnings:
            if lines:
                lines.append("")
            lines.append("**Warnings:**")
            for w in self.meta.warnings:
                lines.append(f"- {w}")
        return "\n".join(lines)


def _human_size(n: int) -> str:
    """Render a byte count as ``1.2 MB`` / ``938.8 KB`` / ``420 B``."""
    if n < 1024:
        return f"{n} B"
    size = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TB"


def _escape_table_cell(v: str) -> str:
    """Escape a value for safe inclusion in a single Markdown table cell.

    Replaces ``|`` with ``\\|`` (table column separator) and collapses
    embedded newlines to spaces so a rogue multi-line ``author`` or
    ``title`` value never breaks the table's single-row shape.
    """
    return v.replace("|", "\\|").replace("\n", " ").replace("\r", " ")
