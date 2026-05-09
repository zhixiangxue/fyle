"""HTML reader backed by ``markdownify``.

Strategy:
- Decode bytes (UTF-8 BOM-aware; latin-1 fallback via the plaintext helper).
- Strip ``<head>`` before conversion. ``markdownify`` otherwise inlines
  ``<title>`` / ``<meta>`` text into the body output, which pollutes the
  Markdown. We use BeautifulSoup to remove the head cleanly (and to pull
  ``<title>`` out separately for ``meta.title``).
- Convert the body to Markdown via ``markdownify`` with ``heading_style="ATX"``
  (the ``# Heading`` form, which is the dialect we normalise on everywhere).
- Structural extraction (tables, images) is delegated to the shared
  ``_md_structure`` module, so HTML, DOCX and Markdown readers all present
  a consistent ``doc.tables`` / ``doc.images`` surface.

File naming rule: ``markdownify.py`` — the core driver for HTML → Markdown.
BeautifulSoup is a pre-processor (strip head, read title) and therefore
does not determine the file name.
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


class HtmlReader(Reader):
    name = "markdownify"
    formats = ("html",)
    is_default = True

    def read(self, data: bytes, *, source_name: Optional[str] = None, **_) -> Document:
        try:
            from markdownify import markdownify as _to_md
        except ImportError as e:
            raise ParseError(
                "markdownify is required for HTML parsing: pip install markdownify"
            ) from e

        warnings: list[str] = []
        html, decode_warning = _decode_text(data)
        if decode_warning:
            warnings.append(decode_warning)

        # Extract <title> and strip <head> so markdownify does not leak head
        # contents into the body.
        title, body_html = _prepare_html(html, warnings)

        try:
            md = _to_md(body_html, heading_style="ATX")
        except Exception as e:
            raise ParseError(f"markdownify failed: {e}") from e

        if not title and source_name:
            title = Path(source_name).stem or None

        tables = extract_tables(md, page=1, warnings=warnings)
        images = extract_images(md, page=1, warnings=warnings, include_html_img=True)

        try:
            page = Page(text=md, number=1, tables=tables, images=images)
            meta = Meta(
                format="html",
                pages=1,
                size=len(data),
                title=title,
                reader=self.name,
                created_at=datetime.now(timezone.utc),
                warnings=warnings,
            )
            return Document(pages=[page], meta=meta)
        except Exception as e:  # pragma: no cover - defensive
            raise ParseError(f"html reader failed to build Document: {e}") from e


def _prepare_html(html: str, warnings: list[str]) -> tuple[Optional[str], str]:
    """Return ``(title, body_html)`` — ``title`` may be ``None``.

    Uses BeautifulSoup if available, otherwise degrades to returning the raw
    HTML and no title (with a warning). Never raises.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        warnings.append("beautifulsoup4 not installed; skipping <head> removal")
        return None, html
    try:
        soup = BeautifulSoup(html, "html.parser")
        # Pull the title before removing <head>.
        title: Optional[str] = None
        if soup.title and soup.title.string:
            s = soup.title.string.strip()
            title = s or None
        # Remove <head> entirely so its contents don't end up in the body
        # Markdown. Remove stray <script> / <style> too, since markdownify
        # will otherwise emit their raw contents as text.
        if soup.head is not None:
            soup.head.decompose()
        for tag in soup.find_all(["script", "style", "noscript"]):
            tag.decompose()
        # Prefer the body subtree if present; otherwise fall back to the
        # whole (now head-less) document.
        body = soup.body
        body_html = str(body) if body is not None else str(soup)
        return title, body_html
    except Exception as e:
        warnings.append(f"HTML pre-processing failed: {e}")
        return None, html
