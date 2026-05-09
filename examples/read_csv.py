"""Interactive CSV reader example.

Usage:
    python examples/read_csv.py

Accepts ``.csv`` files, local path or ``http(s)://`` URL. The CSV is
rendered as a single Markdown pipe table via ``tabulate``. Numeric-looking
cells keep their leading zeros (zip codes / phone numbers); literal ``|``
is escaped to ``\\|``; embedded newlines become ``<br>``.
"""
from _common import run


PROMPT = "Enter a .csv source (local path or http(s):// URL), or blank to quit."


if __name__ == "__main__":
    raise SystemExit(run(PROMPT))
