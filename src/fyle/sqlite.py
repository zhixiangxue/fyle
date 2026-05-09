"""Read-only SQLite query helpers, intended for LLM tool-call use.

Why this module exists
----------------------
``fyle.open("x.sqlite")`` returns a ``Document`` that previews every table's
schema plus a handful of sample rows. That is the right default: it gives
an LLM enough context to understand the database in a single prompt.

It is **not** enough when the LLM actually needs to answer questions from
the data ("how many orders above $100 last month?"). For that scenario, an
agent framework wires up tool calls — one tool-call per SQL query — and
this module provides the three read-only primitives that cover the vast
majority of such cases:

- :func:`tables`  — list user tables and views.
- :func:`schema`  — describe the columns of a table or view.
- :func:`query`   — run an arbitrary read-only SQL statement and format the
  result as a Markdown pipe table.

Design rules
------------
- **Read-only**. The underlying connection is opened with
  ``mode=ro&immutable=1``, so ``INSERT`` / ``UPDATE`` / ``DELETE`` / DDL
  statements raise ``sqlite3.OperationalError`` from SQLite itself. We do
  not offer an ``execute`` counterpart: writes fall outside fyle's "open
  anything, read everything" scope.
- **No row cap**. The caller (or the LLM's own ``LIMIT`` clause) decides
  how much data to pull. Silent truncation would be a footgun — better to
  let the caller see the real shape of their data.
- **No cell truncation**. Cell values are stringified verbatim; ``None``
  becomes the literal string ``"NULL"`` to keep the rendered table
  unambiguous.
- **Stateless API**. Every call opens and closes its own connection. There
  is no session object to manage, which matches how LLM tools typically
  invoke Python functions (fresh arguments per call).

Parameter binding uses SQLite's positional ``?`` placeholder, same as the
``sqlite3`` stdlib module.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional, Union


__all__ = ["tables", "schema", "query"]


def _connect(path: Union[str, Path]) -> sqlite3.Connection:
    """Open ``path`` as a read-only immutable SQLite connection.

    ``immutable=1`` promises the file will not change on disk and lets
    SQLite skip lock acquisition, which matters when the same file is
    concurrently opened by other processes.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"SQLite file not found: {p}")
    uri = f"file:{p}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def _render_md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render an arbitrarily wide/long GFM pipe table.

    Consistent with the rest of fyle's Markdown output so results can be
    pasted straight back into an LLM prompt.
    """
    if not headers:
        return "(no columns)"
    try:
        from tabulate import tabulate as _tabulate
        return _tabulate(rows, headers=headers, tablefmt="github")
    except ImportError:
        esc = lambda s: str(s).replace("|", "\\|")
        out = ["| " + " | ".join(esc(h) for h in headers) + " |"]
        out.append("|" + "|".join(["---"] * len(headers)) + "|")
        for row in rows:
            out.append("| " + " | ".join(esc(c) for c in row) + " |")
        return "\n".join(out)


def _stringify_row(row) -> list[str]:
    """Format a single DB row. ``None`` -> ``"NULL"``; no truncation."""
    return ["NULL" if v is None else str(v) for v in row]


def tables(path: Union[str, Path]) -> list[str]:
    """Return every user table and view name, alphabetically.

    System tables (``sqlite_master``, ``sqlite_sequence`` and friends —
    anything prefixed with ``sqlite_``) are filtered out.
    """
    conn = _connect(path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table', 'view') "
            "AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def schema(path: Union[str, Path], table: str) -> str:
    """Describe the columns of ``table`` as a Markdown pipe table.

    Columns: ``column | type | nullable | default | pk``.
    Raises ``ValueError`` if the table/view is unknown.
    """
    conn = _connect(path)
    try:
        cur = conn.cursor()
        cur.execute(f'PRAGMA table_info("{table}")')
        rows = cur.fetchall()
        if not rows:
            raise ValueError(f"Unknown table or view: {table!r}")
        headers = ["column", "type", "nullable", "default", "pk"]
        body: list[list[str]] = []
        for _cid, col_name, col_type, notnull, dflt, pk in rows:
            body.append([
                str(col_name),
                str(col_type or ""),
                "NO" if notnull else "YES",
                "" if dflt is None else str(dflt),
                str(pk) if pk else "",
            ])
        return _render_md_table(headers, body)
    finally:
        conn.close()


def query(
    path: Union[str, Path],
    sql: str,
    params: Optional[list] = None,
) -> str:
    """Run a read-only SQL statement and return results as a Markdown table.

    The connection is opened in read-only mode, so any write attempt (INSERT,
    UPDATE, DELETE, DDL) raises ``sqlite3.OperationalError`` at execute time.

    Args:
        path:   Filesystem path to the SQLite database.
        sql:    SQL text. Use ``?`` placeholders for parameters.
        params: Optional positional parameters for the ``?`` placeholders.

    Returns:
        A Markdown pipe table including headers and every returned row, plus
        a trailing ``(N rows)`` summary. For statements that return no column
        set (e.g. ``PRAGMA`` variants that yield nothing), returns a short
        informational string.

    Deliberately does not:
        - cap the returned row count (use ``LIMIT`` in your SQL);
        - truncate long cell values.
    """
    conn = _connect(path)
    try:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        headers = [d[0] for d in (cur.description or [])]
        rows_raw = cur.fetchall()
        if not headers:
            return f"(statement returned no columns; {len(rows_raw)} rows affected in read-only session)"
        rows = [_stringify_row(r) for r in rows_raw]
        table = _render_md_table(headers, rows)
        suffix = f"\n\n({len(rows)} row{'s' if len(rows) != 1 else ''})"
        return table + suffix
    finally:
        conn.close()
