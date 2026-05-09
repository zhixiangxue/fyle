"""CSV reader backed by the Python standard library (``csv`` + ``tabulate``).

Strategy:
- Decode bytes (UTF-8 with BOM; latin-1 fallback).
- Use the stdlib ``csv`` module with dialect sniffing to tolerate common
  separators (``,`` / ``;`` / tab / ``|``).
- Emit a single ``Table`` and a single ``Page`` whose ``.text`` is a
  Markdown table produced by ``tabulate`` — never hand-assembled.

Assumption: first row is the header. For header-less CSV a warning is
recorded and the first row is still used as header (downstream can inspect
``table.rows`` for the raw cells if needed).

File naming rule: ``stdlib.py`` — the driver is the stdlib ``csv`` module;
``tabulate`` is a post-processor and does not determine the file name.
``Reader.name`` is ``csv-stdlib`` to keep the registry key unique.
"""
from __future__ import annotations

import csv as _csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tabulate import tabulate

from ..base import Reader
from ..._core.document import Document, Meta, Page, Table
from ...errors import ParseError
from ..text.stdlib import _decode_text


# Dialect sniffer only looks at this many bytes; enough for a realistic CSV header.
_SNIFF_SAMPLE = 4096


def _escape_md_cell(cell: str) -> str:
    """Escape a single cell so it is safe inside a Markdown pipe table.

    Markdown tables cannot carry literal ``|`` or newlines inside a cell.
    We replace ``|`` with ``\\|`` and convert line breaks to ``<br>`` (widely
    supported by Markdown renderers, including GitHub).
    """
    if not isinstance(cell, str):
        cell = "" if cell is None else str(cell)
    return cell.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")


class CsvReader(Reader):
    name = "csv-stdlib"
    formats = ("csv",)
    is_default = True

    def read(self, data: bytes, *, source_name: Optional[str] = None, **_) -> Document:
        warnings: list[str] = []
        text, decode_warning = _decode_text(data)
        if decode_warning:
            warnings.append(decode_warning)

        # Sniff the dialect; fall back to the default ``excel`` (comma) dialect
        # if the sample is too ambiguous.
        sample = text[:_SNIFF_SAMPLE]
        try:
            dialect = _csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except _csv.Error:
            dialect = _csv.excel

        try:
            rows = list(_csv.reader(io.StringIO(text), dialect=dialect))
        except _csv.Error as e:
            raise ParseError(f"csv parse failed: {e}") from e

        if not rows:
            headers: list[str] = []
            body: list[list[str]] = []
            md_table = ""
        else:
            headers = rows[0]
            body = rows[1:]
            # Pre-escape cells for Markdown-table safety before handing off to
            # ``tabulate``. Three hazards that ``tabulate`` itself does *not*
            # handle:
            #   1. a literal ``|`` inside a cell breaks the column structure.
            #   2. a newline inside a cell is not legal in a Markdown table.
            #   3. numeric-looking strings get right-aligned and re-formatted,
            #      which silently drops leading zeros (zip codes, phone
            #      numbers). ``disable_numparse=True`` fixes that.
            safe_headers = [_escape_md_cell(h) for h in headers]
            safe_body = [[_escape_md_cell(c) for c in row] for row in body]
            md_table = tabulate(
                safe_body,
                headers=safe_headers,
                tablefmt="pipe",
                disable_numparse=True,
            )

        title: Optional[str] = None
        if source_name:
            try:
                title = Path(source_name).stem or None
            except (TypeError, ValueError):
                title = None

        try:
            table = Table(text=md_table, rows=body, headers=headers, page=1)
            page = Page(text=md_table, number=1, tables=[table])
            meta = Meta(
                format="csv",
                pages=1,
                size=len(data),
                title=title,
                reader=self.name,
                created_at=datetime.now(timezone.utc),
                warnings=warnings,
            )
            return Document(pages=[page], meta=meta)
        except Exception as e:  # pragma: no cover - defensive
            raise ParseError(f"csv-stdlib reader failed to build Document: {e}") from e
