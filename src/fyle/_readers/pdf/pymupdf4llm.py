"""PDF reader powered by ``pymupdf4llm`` — the default PDF reader.

Rationale: ``pymupdf4llm`` (maintained by the PyMuPDF team) already produces
LLM-friendly Markdown from PDFs and handles headings, lists, tables, and
embedded images. It is substantially less work than rebuilding those heuristics
on top of raw PyMuPDF.

Strategy:
- Open the PDF once with ``pymupdf`` to read document-level metadata.
- Call ``pymupdf4llm.to_markdown(doc, page_chunks=True, embed_images=True)`` to
  get per-page Markdown with images inlined as base64 data URLs.
- Populate ``Page.text`` from the returned per-page Markdown. ``Page.tables``
  and ``Page.images`` are back-filled via the shared ``_md_structure``
  extractor (GFM table tokens + native / HTML image references) so the
  surface stays consistent with the Markdown / DOCX / HTML readers.
"""
from __future__ import annotations

import contextlib
import os
import sys
from datetime import datetime
from typing import Iterator, Optional

from ..._core.document import Document, Meta, Page
from ...errors import ParseError
from ..base import Reader
from .._md_structure import extract_images, extract_tables


class PyMuPdf4LlmReader(Reader):
    name = "pymupdf4llm"
    formats = ("pdf",)
    is_default = True

    def read(self, data: bytes, *, source_name: Optional[str] = None, **_) -> Document:
        try:
            import pymupdf as fitz  # PyMuPDF >= 1.24
        except ImportError:
            try:
                import fitz  # type: ignore[no-redef]
            except ImportError as e:
                raise ParseError(
                    "PyMuPDF (pymupdf) is required: pip install pymupdf"
                ) from e

        try:
            import pymupdf4llm  # noqa: F401
        except ImportError as e:
            raise ParseError(
                "pymupdf4llm is required for PDF parsing: pip install pymupdf4llm"
            ) from e

        warnings: list[str] = []

        try:
            pdf = fitz.open(stream=data, filetype="pdf")
        except Exception as e:
            raise ParseError(f"Failed to open PDF: {e}") from e

        try:
            try:
                # pymupdf4llm + MuPDF emit a ``=== Document parser
                # messages ===`` banner (e.g. "Using Tesseract for OCR
                # processing.", "OCR on page.number=0/1.") during
                # ``to_markdown``. Some lines come from Python
                # ``print`` calls, but the per-page OCR progress and
                # MuPDF warnings are emitted by the C extension
                # directly via ``fprintf(stderr, ...)`` / ``stdout``,
                # which ``contextlib.redirect_stdout`` cannot touch
                # because it only rebinds ``sys.stdout`` at the Python
                # level. We therefore redirect file descriptors 1 and 2
                # at the OS level — the only way to silence a C
                # extension's writes — for the duration of the call.
                # ``show_progress=False`` still helps but does not
                # cover the banner or the OCR lines.
                with _silence_fds():
                    chunks = pymupdf4llm.to_markdown(
                        pdf,
                        page_chunks=True,
                        embed_images=True,
                        write_images=False,
                        show_progress=False,
                    )
            except Exception as e:
                raise ParseError(f"pymupdf4llm.to_markdown failed: {e}") from e

            pages: list[Page] = []
            for idx, chunk in enumerate(chunks, start=1):
                text = (chunk.get("text") or "").strip()
                tables = extract_tables(text, page=idx, warnings=warnings)
                images = extract_images(
                    text, page=idx, warnings=warnings, include_html_img=True
                )
                pages.append(Page(text=text, number=idx, tables=tables, images=images))

            if not pages:
                # Degenerate case: pymupdf4llm returned nothing. Keep at least
                # one empty page so ``doc.pages`` is never an empty list.
                pages.append(Page(text="", number=1))
                warnings.append("pymupdf4llm returned no page chunks")

            md = pdf.metadata or {}
            title = _clean(md.get("title"))
            author = _clean(md.get("author"))
            created_at = _parse_pdf_date(md.get("creationDate"))

            if not title and source_name:
                title = source_name

            meta = Meta(
                format="pdf",
                pages=len(pages),
                size=len(data),
                title=title,
                author=author,
                created_at=created_at,
                reader=self.name,
                warnings=warnings,
            )
        finally:
            try:
                pdf.close()
            except Exception:
                pass

        return Document(pages=pages, meta=meta)


def _clean(value) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="ignore")
        except Exception:
            return None
    s = str(value).strip()
    return s or None


@contextlib.contextmanager
def _silence_fds() -> Iterator[None]:
    """Redirect fds 1 and 2 to ``/dev/null`` at the OS level.

    ``contextlib.redirect_stdout`` only rebinds ``sys.stdout`` at the
    Python level, so any C extension that calls ``fprintf(stdout, ...)``
    or ``fprintf(stderr, ...)`` directly (MuPDF warnings, the Tesseract
    OCR progress banner, etc.) bypasses it. Duplicating ``/dev/null``
    onto file descriptors 1 and 2 is the only way to silence those
    writes without a third-party dependency. fds are restored on exit
    even if the wrapped call raises.
    """
    # Flush Python-level buffers so nothing we care about ends up
    # arriving at the silenced fds.
    sys.stdout.flush()
    sys.stderr.flush()
    saved_stdout_fd = os.dup(1)
    saved_stderr_fd = os.dup(2)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)
        try:
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(saved_stdout_fd, 1)
            os.dup2(saved_stderr_fd, 2)
    finally:
        os.close(devnull_fd)
        os.close(saved_stdout_fd)
        os.close(saved_stderr_fd)


def _parse_pdf_date(s) -> Optional[datetime]:
    """Parse the PDF standard date format ``D:YYYYMMDDHHmmSS+OFFSET``.

    Returns ``None`` on any parse failure.
    """
    if not s:
        return None
    if isinstance(s, bytes):
        try:
            s = s.decode("utf-8", errors="ignore")
        except Exception:
            return None
    s = str(s).strip()
    if s.startswith("D:"):
        s = s[2:]
    if len(s) >= 14:
        try:
            return datetime.strptime(s[:14], "%Y%m%d%H%M%S")
        except ValueError:
            pass
    if len(s) >= 8:
        try:
            return datetime.strptime(s[:8], "%Y%m%d")
        except ValueError:
            pass
    return None
