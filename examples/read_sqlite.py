"""Interactive SQLite reader example.

Usage:
    python examples/read_sqlite.py

Accepts ``.db`` / ``.sqlite`` / ``.sqlite3`` files, local path or
``http(s)://`` URL. Each user table (and view) becomes one ``Page``:
``page.name`` is the table name, ``page.text`` is Markdown combining
the column schema with a small sample of rows.

For real queries against the same database, ``fyle.sqlite.query(path,
sql)`` is the read-only companion API — it shares this reader's format
contract but does not cap rows or truncate cells, so the LLM can phrase
``LIMIT`` clauses itself.

Where to get a test database
----------------------------
Rather than ship a synthetic fixture, grab a real SQLite file from
Kaggle. We pin a single database on purpose so the SQL demo below
can target a known schema:

    European Soccer Database (~300 MB, 7 tables, rich schema)
    https://www.kaggle.com/datasets/hugomathien/soccer
    → download ``database.sqlite`` and drop it onto this prompt.

Kaggle requires a free account. Once downloaded, just drag the file
into the terminal — no unzipping needed if the archive already
contains ``database.sqlite`` directly.

What this example demonstrates
------------------------------
1. ``fyle.open(path)`` — every table/view becomes a ``Page`` with
   schema + 10 sample rows (LLM context).
2. ``doc.table(name).query(sql)`` — read-only SQL against the same
   file, unbounded (no row cap, no cell truncation). The SQL is
   free-form; ``table(name)`` is a conceptual starting point, not a
   scope restriction (``.query()`` can JOIN any tables in the db).
"""
import sys

import fyle

from _common import _print_summary, _prompt_source


PROMPT = (
    "Enter the path to the European Soccer Database (database.sqlite from Kaggle), "
    "or blank to quit."
)

# Pre-canned SQL that exercises the European Soccer Database schema.
# Each tuple is (starting_table_for_doc.table(), label, sql).
# Keeping these table/column names hard-coded is the point of pinning
# the dataset: the demo would be meaningless against an arbitrary .db.
DEMO_QUERIES = [
    (
        "Country",
        "Countries in the database",
        "SELECT id, name FROM Country ORDER BY name",
    ),
    (
        "Match",
        "Matches per season",
        "SELECT season, COUNT(*) AS matches FROM Match GROUP BY season ORDER BY season",
    ),
    (
        "Player",
        "Top 5 tallest players",
        "SELECT player_name, height, weight FROM Player "
        "ORDER BY height DESC, player_name ASC LIMIT 5",
    ),
    (
        "Player",
        "Write attempt (should fail — read-only mode)",
        "DELETE FROM Player",
    ),
]


def _run_sql_demo(doc: fyle.Document) -> None:
    """Drive the canned queries through ``doc.table(name).query(sql)``."""
    print()
    print("=" * 60)
    print("  SQL query demo via doc.table(name).query(sql) (read-only)")
    print("=" * 60)
    print("  (queries assume the European Soccer Database schema)")
    for start_table, label, sql in DEMO_QUERIES:
        print()
        print(f"-- {label}")
        print(f"   doc.table({start_table!r}).query(...)")
        print(f"   SQL: {sql}")
        try:
            handle = doc.table(start_table)
            md = handle.query(sql)
        except Exception as e:  # noqa: BLE001 — surface whatever blew up
            print(f"   [{type(e).__name__}] {e}")
            continue
        for line in md.splitlines():
            print(f"   {line}")


def main() -> int:
    src = _prompt_source(PROMPT)
    if not src:
        print("No source given. Bye.")
        return 0

    print(f"\nOpening: {src}\n")
    try:
        doc = fyle.open(src)
    except fyle.DownloadError as e:
        print(f"[DownloadError] failed to fetch URL: {e}", file=sys.stderr)
        return 1
    except fyle.UnsupportedFormatError as e:
        print(f"[UnsupportedFormatError] {e}", file=sys.stderr)
        return 1
    except fyle.ReaderNotFoundError as e:
        print(f"[ReaderNotFoundError] {e}", file=sys.stderr)
        return 1
    except fyle.ParseError as e:
        print(f"[ParseError] {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"[FileNotFoundError] {e}", file=sys.stderr)
        return 1

    _print_summary(doc)

    # ``doc.table(...).query(...)`` works whether the source was a local
    # file or a URL — the reader already materialised a temp db under
    # the Document, and the Document owns its lifetime.
    if hasattr(doc, "table"):
        try:
            _run_sql_demo(doc)
        finally:
            # Eager cleanup of the backing temp db file. Not strictly
            # required (GC would also trigger the finalizer), but it
            # keeps the example's footprint tight.
            if hasattr(doc, "close"):
                doc.close()
    else:
        print("\n(skipping SQL demo: this Document does not expose .table())")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
