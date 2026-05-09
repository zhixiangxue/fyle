"""DOCX reader backed by ``mammoth``.

Pipeline: DOCX → HTML (via ``mammoth.convert_to_html``) → Markdown (via
``markdownify``).

Why the two-stage pipeline rather than ``mammoth.convert_to_markdown``?
``mammoth`` 's Markdown target is known to be lossy on tables: it emits
each cell as a separate paragraph instead of a Markdown pipe table. Its
HTML target, by contrast, is faithful — tables render as real ``<table>``
elements. ``markdownify`` then converts HTML tables into Markdown pipe
tables cleanly. Each library does what it is good at.

Inline images survive the pipeline: ``mammoth`` embeds them as
``data:image/...;base64,...`` URLs in the HTML, and ``markdownify``
preserves those in the Markdown output. Structural extraction (tables,
images) is delegated to the shared ``_md_structure`` module so DOCX,
HTML and Markdown readers all present a consistent ``doc.tables`` /
``doc.images`` surface.

All content lives in a single ``Page``. DOCX has no native pagination
(page breaks in Word are rendering artifacts, not data), so v0.2 returns
``pages=[one_page]`` rather than forging a page number. This is noted in
``meta.warnings`` for transparency.

``python-docx`` is used only for core properties (title / author /
created_at) — ``mammoth`` does not expose those.
"""
from __future__ import annotations

import io
from datetime import timezone
from pathlib import Path
from typing import Optional

from ..base import Reader
from ..._core.document import Document, Meta, Page
from ...errors import ParseError
from .._md_structure import extract_images, extract_tables


class DocxReader(Reader):
    name = "mammoth"
    formats = ("docx",)
    is_default = True

    def read(self, data: bytes, *, source_name: Optional[str] = None, **_) -> Document:
        try:
            import mammoth
        except ImportError as e:
            raise ParseError(
                "mammoth is required for DOCX parsing: pip install mammoth"
            ) from e
        try:
            from markdownify import markdownify as _to_md
        except ImportError as e:
            raise ParseError(
                "markdownify is required for DOCX parsing: pip install markdownify"
            ) from e

        warnings: list[str] = []

        # Stage 1: DOCX -> HTML via mammoth (tables, images, headings intact).
        try:
            result = mammoth.convert_to_html(io.BytesIO(data))
        except Exception as e:
            raise ParseError(f"mammoth.convert_to_html failed: {e}") from e
        html = result.value or ""
        for msg in getattr(result, "messages", []) or []:
            m_type = getattr(msg, "type", "warning")
            m_text = getattr(msg, "message", str(msg))
            if m_type in ("warning", "error"):
                warnings.append(f"mammoth: {m_text}")

        # Stage 2: HTML -> Markdown via markdownify. ``heading_style="ATX"``
        # selects ``# Heading`` (the dialect we normalise on everywhere).
        try:
            md = _to_md(html, heading_style="ATX")
        except Exception as e:
            raise ParseError(f"markdownify failed on DOCX HTML: {e}") from e

        # 2b. Core metadata via python-docx (best-effort).
        title, author, created_at = _read_core_props(data, warnings)

        if not title and source_name:
            title = Path(source_name).stem or None

        # 3. Structural extraction from the produced Markdown. The DOCX
        # pipeline yields standard GFM pipe tables (from markdownify) and
        # ``![alt](data:...)`` image references, both handled by the
        # shared extractor.
        tables = extract_tables(md, page=1, warnings=warnings)
        images = extract_images(md, page=1, warnings=warnings, include_html_img=True)

        try:
            page = Page(text=md, number=1, tables=tables, images=images)
            meta = Meta(
                format="docx",
                pages=1,
                size=len(data),
                title=title,
                author=author,
                created_at=created_at,
                reader=self.name,
                warnings=warnings,
            )
            return Document(pages=[page], meta=meta)
        except Exception as e:  # pragma: no cover - defensive
            raise ParseError(f"docx reader failed to build Document: {e}") from e


def _read_core_props(data: bytes, warnings: list[str]):
    """Best-effort read of DOCX core properties via python-docx."""
    try:
        from docx import Document as _DocxDoc
    except ImportError:
        warnings.append("python-docx not installed; skipping DOCX metadata")
        return None, None, None
    try:
        d = _DocxDoc(io.BytesIO(data))
        props = d.core_properties
        title = (props.title or None) or None
        author = (props.author or None) or None
        created_at = props.created
        # Naive datetimes: stamp as UTC so Meta.created_at is always tz-aware.
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return title, author, created_at
    except Exception as e:
        warnings.append(f"DOCX metadata read failed: {e}")
        return None, None, None
