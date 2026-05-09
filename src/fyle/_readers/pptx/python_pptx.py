"""PowerPoint (.pptx) reader backed by ``python-pptx``.

Each slide becomes one ``Page``:
- ``page.number`` is the slide's 1-based index.
- ``page.name`` holds the slide title (from the title placeholder) when
  present. Same field as the sheet name for XLSX \u2014 kept consistent
  rather than inventing a ``Slide`` type.
- ``page.text`` is Markdown assembled from the slide's text frames,
  bullet lists, tables and images, in slide order.
- ``page.tables`` and ``page.images`` are populated in parallel so
  downstream code can access structural data without re-parsing.

Tables go through ``tabulate`` (GFM pipe format); images are embedded
as ``data:image/...;base64,...`` URLs so the document is self-contained
and can be fed directly to a multimodal LLM.

File naming rule: ``python_pptx.py`` \u2014 the core driver is ``python-pptx``.
(Module name uses ``_`` rather than ``-`` because Python identifiers
cannot contain hyphens.)
"""
from __future__ import annotations

import base64
import io
from datetime import timezone
from pathlib import Path
from typing import Any, Optional

from ..base import Reader
from ..._core.document import Document, Image, Meta, Page, Table
from ...errors import ParseError


class PptxReader(Reader):
    name = "python-pptx"
    formats = ("pptx",)
    is_default = True

    def read(self, data: bytes, *, source_name: Optional[str] = None, **_) -> Document:
        try:
            from pptx import Presentation
        except ImportError as e:
            raise ParseError(
                "python-pptx is required for PPTX parsing: pip install python-pptx"
            ) from e
        try:
            from pptx.enum.shapes import MSO_SHAPE_TYPE
        except ImportError as e:  # pragma: no cover
            raise ParseError(f"python-pptx import failed: {e}") from e

        warnings: list[str] = []

        try:
            prs = Presentation(io.BytesIO(data))
        except Exception as e:
            raise ParseError(f"python-pptx failed to open PPTX: {e}") from e

        pages: list[Page] = []
        for idx, slide in enumerate(prs.slides, start=1):
            page = _render_slide(slide, idx, MSO_SHAPE_TYPE, warnings)
            pages.append(page)

        if not pages:
            pages.append(Page(text="", number=1))
            warnings.append("pptx: no slides found")

        title, author, created_at = _read_core_props(prs, warnings)

        if not title and source_name:
            try:
                title = Path(source_name).stem or None
            except (TypeError, ValueError):
                title = None

        try:
            meta = Meta(
                format="pptx",
                pages=len(pages),
                size=len(data),
                title=title,
                author=author,
                created_at=created_at,
                reader=self.name,
                warnings=warnings,
            )
            return Document(pages=pages, meta=meta)
        except Exception as e:  # pragma: no cover - defensive
            raise ParseError(f"pptx reader failed to build Document: {e}") from e


def _read_core_props(prs, warnings: list[str]):
    """Best-effort read of PPTX core properties. Never raises."""
    try:
        cp = prs.core_properties
        title = (cp.title or None) or None
        author = (cp.author or None) or None
        created_at = cp.created
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return title, author, created_at
    except Exception as e:
        warnings.append(f"PPTX metadata read failed: {e}")
        return None, None, None


def _render_slide(slide: Any, slide_no: int, MSO_SHAPE_TYPE: Any, warnings: list[str]) -> Page:
    """Walk the slide's shapes and assemble Markdown + structural elements."""
    md_parts: list[str] = []
    tables: list[Table] = []
    images: list[Image] = []

    slide_title = _slide_title(slide)
    if slide_title:
        md_parts.append(f"# {slide_title}")

    for shape in slide.shapes:
        # Skip the title placeholder we already rendered as H1.
        if _is_title_placeholder(shape) and slide_title:
            continue

        try:
            if shape.has_text_frame:
                block = _render_text_frame(shape.text_frame)
                if block:
                    md_parts.append(block)
                continue
            if shape.has_table:
                md, tbl = _render_table(shape.table, slide_no, warnings)
                if tbl is not None:
                    tables.append(tbl)
                if md:
                    md_parts.append(md)
                continue
            if getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.PICTURE:
                md, img = _render_picture(shape, slide_no, warnings)
                if img is not None:
                    images.append(img)
                if md:
                    md_parts.append(md)
                continue
        except Exception as e:
            warnings.append(f"pptx slide {slide_no}: shape render failed: {e}")
            continue

    # Notes are optional; include them at the bottom under a subheading.
    notes = _slide_notes(slide)
    if notes:
        md_parts.append("## Speaker notes")
        md_parts.append(notes)

    page_text = "\n\n".join(p for p in md_parts if p)

    return Page(
        text=page_text,
        number=slide_no,
        name=slide_title or None,
        tables=tables,
        images=images,
    )


def _sanitize(text: str, line_sep: str = "\n") -> str:
    """Normalise PowerPoint control characters in extracted strings.

    PowerPoint stores soft line breaks (``Shift+Enter``) as the vertical tab
    byte ``\\x0b`` (VT) inside a single paragraph. ``python-pptx`` returns
    those verbatim via ``paragraph.text`` / ``text_frame.text``, which leaks
    the raw control byte into our Markdown and into ``Page.name`` / titles.

    We collapse those to ``line_sep``:
    - ``"\n"`` for body / paragraph text — preserves the "line break within
      paragraph" semantics.
    - ``" "`` for titles — a slide title is rendered on one line in Markdown
      anyway, and embedding a newline would break the heading.
    """
    if not text:
        return text
    return text.replace("\x0b", line_sep).replace("\x0c", line_sep)


def _slide_title(slide: Any) -> Optional[str]:
    """Extract the slide title placeholder text, or ``None``."""
    try:
        title_shape = slide.shapes.title
    except Exception:
        return None
    if title_shape is None:
        return None
    try:
        text = (title_shape.text_frame.text or "").strip()
    except Exception:
        return None
    text = _sanitize(text, line_sep=" ").strip()
    return text or None


def _is_title_placeholder(shape: Any) -> bool:
    try:
        if not shape.has_text_frame:
            return False
        ph = getattr(shape, "placeholder_format", None)
        if ph is None:
            return False
        # ``idx == 0`` is the title placeholder across layouts.
        return getattr(ph, "idx", None) == 0
    except Exception:
        return False


def _render_text_frame(tf: Any) -> str:
    """Render a text frame as Markdown paragraphs / bullets.

    Heuristic: paragraphs with ``level > 0`` or short indented content
    become bullet items; others become paragraphs.
    """
    lines: list[str] = []
    for para in tf.paragraphs:
        text = _sanitize((para.text or ""), line_sep="\n").strip()
        if not text:
            continue
        level = getattr(para, "level", 0) or 0
        if level > 0:
            indent = "  " * (level - 0)
            lines.append(f"{indent}- {text}")
        else:
            # Treat a leading dash / bullet glyph as a bullet too.
            if text.startswith(("\u2022", "-", "*")):
                lines.append(f"- {text.lstrip('\u2022-* ').strip()}")
            else:
                lines.append(text)
    return "\n".join(lines)


def _render_table(tbl: Any, slide_no: int, warnings: list[str]) -> tuple[str, Optional[Table]]:
    """Render a python-pptx table as a GFM pipe table (via tabulate)."""
    try:
        from tabulate import tabulate as _tabulate
    except ImportError:
        warnings.append("tabulate not installed; skipping pptx table render")
        return "", None

    rows_raw: list[list[str]] = []
    for row in tbl.rows:
        row_cells: list[str] = []
        for cell in row.cells:
            try:
                cell_text = _sanitize((cell.text or ""), line_sep="\n").strip()
            except Exception:
                cell_text = ""
            row_cells.append(cell_text)
        rows_raw.append(row_cells)

    if not rows_raw:
        return "", None

    headers = rows_raw[0]
    body = rows_raw[1:]
    try:
        md = _tabulate(body, headers=headers, tablefmt="github")
    except Exception as e:
        warnings.append(f"pptx slide {slide_no}: table render failed: {e}")
        return "", None

    return md, Table(text=md, rows=body, headers=headers, page=slide_no)


def _render_picture(shape: Any, slide_no: int, warnings: list[str]) -> tuple[str, Optional[Image]]:
    """Extract a picture shape's bytes into a ``data:`` URL and Markdown token."""
    try:
        image = shape.image
    except Exception as e:
        warnings.append(f"pptx slide {slide_no}: picture access failed: {e}")
        return "", None

    try:
        blob: bytes = image.blob or b""
        content_type: str = image.content_type or "application/octet-stream"
    except Exception as e:
        warnings.append(f"pptx slide {slide_no}: picture read failed: {e}")
        return "", None

    if not blob:
        return "", None

    b64 = base64.b64encode(blob).decode("ascii")
    data_url = f"data:{content_type};base64,{b64}"

    caption: Optional[str] = None
    name = getattr(shape, "name", "") or ""
    if name:
        caption = name

    md_token = f"![{caption or ''}]({data_url})"
    img = Image(data_url=data_url, data=blob, caption=caption, page=slide_no)
    return md_token, img


def _slide_notes(slide: Any) -> str:
    """Return the slide's speaker notes as plain text, or ``""``."""
    try:
        if not slide.has_notes_slide:
            return ""
        notes_tf = slide.notes_slide.notes_text_frame
        return _sanitize((notes_tf.text or ""), line_sep="\n").strip()
    except Exception:
        return ""
