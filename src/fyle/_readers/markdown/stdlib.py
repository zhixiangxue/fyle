"""Markdown reader backed by the Python standard library.

For ``.md`` / ``.markdown`` inputs the content *is already* our target
representation, so ``Page.text`` is a **byte-preserving passthrough** of
the decoded source. On top of that passthrough we populate ``doc.tables``
and ``doc.images`` via the shared Markdown structure extractor
(``_md_structure``), which delegates to ``markdown-it-py`` + BeautifulSoup.

File naming rule: ``stdlib.py`` — the *core* dependency is the Python
standard library (decoding). ``markdown-it-py`` and BeautifulSoup are
ancillary parsers used for structural extraction and do not determine the
file name.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..base import Reader
from ..._core.document import Document, Meta, Page
from ...errors import ParseError
from .._md_structure import extract_images, extract_tables
from ..text.stdlib import _decode_text


class MarkdownReader(Reader):
    name = "markdown-stdlib"
    formats = ("markdown",)
    is_default = True

    def read(self, data: bytes, *, source_name: Optional[str] = None, **_) -> Document:
        warnings: list[str] = []
        text, decode_warning = _decode_text(data)
        if decode_warning:
            warnings.append(decode_warning)

        title: Optional[str] = None
        if source_name:
            try:
                title = Path(source_name).stem or None
            except (TypeError, ValueError):
                title = None

        tables = extract_tables(text, page=1, warnings=warnings)
        images = extract_images(text, page=1, warnings=warnings, include_html_img=True)

        try:
            page = Page(text=text, number=1, tables=tables, images=images)
            meta = Meta(
                format="markdown",
                pages=1,
                size=len(data),
                title=title,
                reader=self.name,
                created_at=datetime.now(timezone.utc),
                warnings=warnings,
            )
            return Document(pages=[page], meta=meta)
        except Exception as e:  # pragma: no cover - defensive
            raise ParseError(f"markdown-stdlib reader failed: {e}") from e
