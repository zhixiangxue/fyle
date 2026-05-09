"""SQLite reader backed by Python's standard library (``sqlite3``).

Strategy:
- SQLite ``.db`` / ``.sqlite`` / ``.sqlite3`` files are a native fyle input:
  a single-file database is still a *file*, so it fits ``fyle.open``.
- We produce a **read-only schema overview** with a tiny sample of rows per
  table/view, so an LLM can understand what the database holds without
  pulling the entire dataset. Actual ad-hoc querying is offered through
  ``fyle.sqlite`` (``tables`` / ``schema`` / ``query``), which is a thin
  wrapper around ``sqlite3`` intended for tool-call use.

Per-table Markdown layout:

    # {table_name}

    **Schema**

    | column | type | nullable | default | pk |
    |---|---|---|---|---|
    ...

    **Sample rows** (10 of N)

    | col1 | col2 | ... |
    |---|---|---|
    ...

- ``page.number`` is the table's position in alphabetical order.
- ``page.name`` is the table or view name (reuses the ``Page.name`` slot
  we already use for XLSX sheets and PPTX slide titles).
- ``page.tables`` always carries two ``Table`` objects: ``[schema, sample]``
  so callers can consume the data without re-parsing Markdown.
- ``page.text`` embeds both tables plus the row-count summary.

Sample cap is **10 rows** by design — the reader exists to produce a
compact prompt context, not to dump data. Full scans belong to the
``fyle.sqlite`` query helper (or an external tool) where the LLM
itself decides the row count via ``LIMIT``.

File naming rule: ``stdlib.py`` — the core driver is the Python standard
library's ``sqlite3`` module.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import weakref
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..base import Reader
from ..._core.document import Document, Meta, Page, Table
from ...errors import ParseError


# Number of rows previewed per table/view inside the Document. Kept small
# on purpose: this reader's job is to give an LLM enough shape to reason
# about schema. Callers who want more data should use ``fyle.sqlite.query``
# or the ``doc.table(name).query(sql)`` fluent API.
_SAMPLE_ROWS = 10


class SqliteTable:
    """Interactive handle for one table/view inside a :class:`SqliteDocument`.

    Returned by ``doc.table(name)``. Deliberately *not* a
    :class:`fyle._core.document.Table`: that one is a Pydantic value object
    used across every reader for schema + data rows. This class instead
    bundles a table name with its parent database path so an LLM can chain
    ``.query(sql)`` / ``.schema()`` off a single reference.

    The SQL passed to :meth:`query` is free-form — it can JOIN other tables
    in the same database. ``table(name)`` is a starting point for the LLM's
    train of thought, not a scope restriction.
    """

    __slots__ = ("name", "_db_path")

    def __init__(self, name: str, db_path: str) -> None:
        self.name = name
        self._db_path = db_path

    def query(self, sql: str, params: Optional[list] = None) -> str:
        """Run read-only SQL against the parent database. Returns Markdown."""
        from ... import sqlite as _fyle_sqlite

        return _fyle_sqlite.query(self._db_path, sql, params)

    def schema(self) -> str:
        """Return this table's column schema as a Markdown pipe table."""
        from ... import sqlite as _fyle_sqlite

        return _fyle_sqlite.schema(self._db_path, self.name)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"SqliteTable(name={self.name!r})"


class SqliteDocument(Document):
    """Document subclass returned by :class:`SqliteReader`.

    Adds :meth:`table` for chained SQL access and manages the lifetime of
    the backing temporary database file. ``sqlite3`` only opens databases
    from a filesystem path, so fyle spills the input bytes to a temp file
    and keeps it alive for the Document's lifetime; cleanup is triggered
    by garbage collection, an explicit :meth:`close`, or a ``with`` block.
    """

    # ``__weakref__`` is required so ``weakref.finalize`` can attach to
    # an instance whose parent class already uses ``__slots__``.
    __slots__ = ("_db_path", "_table_names", "_finalizer", "__weakref__")

    def __init__(
        self,
        *,
        pages: list,
        meta: Meta,
        db_path: str,
        table_names: list[str],
    ) -> None:
        super().__init__(pages=pages, meta=meta)
        self._db_path = db_path
        self._table_names = frozenset(table_names)
        self._finalizer = weakref.finalize(self, _unlink_quiet, db_path)

    def table(self, name: str) -> SqliteTable:
        """Return a handle to ``name`` so the caller can run SQL against it.

        Raises ``KeyError`` if ``name`` is not a known table or view in
        this database. The available names are exactly the ones present
        as ``page.name`` on ``doc.pages``.
        """
        if name not in self._table_names:
            raise KeyError(
                f"Unknown table or view: {name!r}. "
                f"Available: {sorted(self._table_names)}"
            )
        return SqliteTable(name, self._db_path)

    def close(self) -> None:
        """Eagerly delete the backing temp db file.

        Safe to call multiple times. Called automatically on ``__exit__``
        and (as a fallback) by the weakref finalizer at GC time.
        """
        self._finalizer()

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


def _unlink_quiet(path: str) -> None:
    """Delete ``path`` if it still exists, swallowing OSError."""
    try:
        os.unlink(path)
    except OSError:
        pass


class SqliteReader(Reader):
    name = "sqlite-stdlib"
    formats = ("sqlite",)
    is_default = True

    def read(self, data: bytes, *, source_name: Optional[str] = None, **_) -> Document:
        if not data:
            raise ParseError("sqlite-stdlib reader: input is empty")
        if not data.startswith(b"SQLite format 3\x00"):
            raise ParseError(
                "sqlite-stdlib reader: not a valid SQLite 3 database "
                "(missing 'SQLite format 3' header)"
            )

        warnings: list[str] = []

        # sqlite3 only opens from a filesystem path, so spill bytes to a
        # temp file and keep it alive for the Document's lifetime. The
        # SqliteDocument takes ownership of cleanup.
        tmp = tempfile.NamedTemporaryFile(
            prefix="fyle-sqlite-", suffix=".db", delete=False
        )
        tmp.write(data)
        tmp.flush()
        tmp.close()
        tmp_path = tmp.name

        handed_off = False
        try:
            uri = f"file:{tmp_path}?mode=ro&immutable=1"
            try:
                conn = sqlite3.connect(uri, uri=True)
            except sqlite3.Error as e:
                raise ParseError(f"sqlite3 failed to open database: {e}") from e
            try:
                pages = _build_pages(conn, warnings)
            finally:
                conn.close()

            if not pages:
                pages.append(
                    Page(text="(database contains no user tables or views)", number=1)
                )
                warnings.append("sqlite: no user tables or views found")

            title: Optional[str] = None
            if source_name:
                try:
                    title = Path(source_name).stem or None
                except (TypeError, ValueError):
                    title = None

            try:
                meta = Meta(
                    format="sqlite",
                    pages=len(pages),
                    size=len(data),
                    title=title,
                    reader=self.name,
                    created_at=datetime.now(timezone.utc),
                    warnings=warnings,
                )
                doc = SqliteDocument(
                    pages=pages,
                    meta=meta,
                    db_path=tmp_path,
                    table_names=[p.name for p in pages if p.name],
                )
            except Exception as e:  # pragma: no cover - defensive
                raise ParseError(f"sqlite reader failed to build Document: {e}") from e

            handed_off = True
            return doc
        finally:
            if not handed_off:
                _unlink_quiet(tmp_path)


def _build_pages(conn: sqlite3.Connection, warnings: list[str]) -> list[Page]:
    """Walk every user table and view, render each as a ``Page``."""
    cur = conn.cursor()
    cur.execute(
        "SELECT name, type FROM sqlite_master "
        "WHERE type IN ('table', 'view') "
        "AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    )
    entries = cur.fetchall()

    pages: list[Page] = []
    for idx, (obj_name, obj_type) in enumerate(entries, start=1):
        try:
            pages.append(_render_object(conn, obj_name, obj_type, idx, warnings))
        except Exception as e:
            warnings.append(f"sqlite: failed to render {obj_type} {obj_name!r}: {e}")
            pages.append(
                Page(text=f"# {obj_name}\n\n(render failed: {e})", number=idx, name=obj_name)
            )
    return pages


def _render_object(
    conn: sqlite3.Connection,
    obj_name: str,
    obj_type: str,
    page_no: int,
    warnings: list[str],
) -> Page:
    """Render one table/view into schema + sample Markdown + structural tables."""
    cur = conn.cursor()

    # Schema via PRAGMA table_info (works for views too — reports column order
    # and types as SQLite sees them).
    schema_headers = ["column", "type", "nullable", "default", "pk"]
    schema_rows: list[list[str]] = []
    try:
        cur.execute(f'PRAGMA table_info("{obj_name}")')
        for _cid, col_name, col_type, notnull, dflt, pk in cur.fetchall():
            schema_rows.append([
                str(col_name),
                str(col_type or ""),
                "NO" if notnull else "YES",
                "" if dflt is None else str(dflt),
                str(pk) if pk else "",
            ])
    except sqlite3.Error as e:
        warnings.append(f"sqlite: PRAGMA table_info({obj_name!r}) failed: {e}")

    # Row count (views report count of their materialised result).
    total_rows: Optional[int] = None
    try:
        cur.execute(f'SELECT COUNT(*) FROM "{obj_name}"')
        total_rows = int(cur.fetchone()[0])
    except sqlite3.Error as e:
        warnings.append(f"sqlite: COUNT(*) on {obj_name!r} failed: {e}")

    # Sample rows.
    sample_headers: list[str] = []
    sample_rows: list[list[str]] = []
    try:
        cur.execute(f'SELECT * FROM "{obj_name}" LIMIT {_SAMPLE_ROWS}')
        sample_headers = [d[0] for d in (cur.description or [])]
        for row in cur.fetchall():
            sample_rows.append(["NULL" if v is None else str(v) for v in row])
    except sqlite3.Error as e:
        warnings.append(f"sqlite: SELECT sample on {obj_name!r} failed: {e}")

    # Markdown assembly.
    md_parts: list[str] = [f"# {obj_name}"]
    kind_hint = "view" if obj_type == "view" else "table"
    if total_rows is not None:
        md_parts.append(f"_type: {kind_hint}, rows: {total_rows}_")
    else:
        md_parts.append(f"_type: {kind_hint}_")

    md_parts.append("**Schema**")
    md_parts.append(_render_md_table(schema_headers, schema_rows))

    if sample_headers:
        shown = len(sample_rows)
        if total_rows is not None and total_rows > shown:
            md_parts.append(f"**Sample rows** ({shown} of {total_rows})")
        else:
            md_parts.append(f"**Sample rows** ({shown})")
        md_parts.append(_render_md_table(sample_headers, sample_rows))

    page_text = "\n\n".join(md_parts)

    schema_table = Table(
        text=_render_md_table(schema_headers, schema_rows),
        rows=schema_rows,
        headers=schema_headers,
        page=page_no,
    )
    tables: list[Table] = [schema_table]
    if sample_headers:
        tables.append(
            Table(
                text=_render_md_table(sample_headers, sample_rows),
                rows=sample_rows,
                headers=sample_headers,
                page=page_no,
            )
        )

    return Page(text=page_text, number=page_no, name=obj_name, tables=tables)


def _render_md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a GFM pipe table. Uses ``tabulate`` when available, else manual."""
    if not headers:
        return "(no columns)"
    try:
        from tabulate import tabulate as _tabulate
        return _tabulate(rows, headers=headers, tablefmt="github")
    except ImportError:
        # Minimal manual fallback; kept simple because ``tabulate`` is a
        # standard fyle dependency so this path is rarely exercised.
        esc = lambda s: str(s).replace("|", "\\|")
        out = ["| " + " | ".join(esc(h) for h in headers) + " |"]
        out.append("|" + "|".join(["---"] * len(headers)) + "|")
        for row in rows:
            out.append("| " + " | ".join(esc(c) for c in row) + " |")
        return "\n".join(out)
