"""Plain-text reader backed by the Python standard library only.

Plain text has no structure. We decode bytes and drop them into ``Page.text``
**unchanged**: no escaping of Markdown-special characters (``*`` / ``_`` /
``#`` / ``|``). Rationale: a ``.txt`` file has no semantic notion of
emphasis or headings; whatever the author typed is what the LLM should see.
Downstream consumers that need true plain-text rendering should treat the
``.text`` as an opaque string, not render it as Markdown.

File naming rule (see design doc §12.0): this reader's file name is the
name of its *core driver library*. Plain text needs nothing beyond the
stdlib, hence ``stdlib.py``. ``Reader.name`` is namespaced with the format
(``"text-stdlib"``) because several readers share the same stdlib driver.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..base import Reader
from ..._core.document import Document, Meta, Page
from ...errors import ParseError


class PlainTextReader(Reader):
    name = "text-stdlib"
    formats = ("text",)
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

        try:
            meta = Meta(
                format="text",
                pages=1,
                size=len(data),
                title=title,
                reader=self.name,
                created_at=datetime.now(timezone.utc),
                warnings=warnings,
            )
            page = Page(text=text, number=1)
            return Document(pages=[page], meta=meta)
        except Exception as e:  # pragma: no cover - defensive
            raise ParseError(f"text-stdlib reader failed: {e}") from e


def _decode_text(data: bytes) -> tuple[str, Optional[str]]:
    """Decode bytes as UTF-8 (with optional BOM); fall back to latin-1 on failure.

    Returns the decoded text plus a warning string (or ``None`` if the decode
    was clean UTF-8).

    Exposed at module level (prefixed ``_``) so that sibling readers
    (``markdown``, ``csv``, ``html``) can reuse the same decoding policy
    without duplicating it.
    """
    try:
        return data.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        return (
            data.decode("latin-1", errors="replace"),
            "text was not valid UTF-8; decoded as latin-1 (some characters may be wrong)",
        )
