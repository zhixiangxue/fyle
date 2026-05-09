"""Interactive XLSX reader example.

Usage:
    python examples/read_xlsx.py

Accepts ``.xlsx`` files, local path or ``http(s)://`` URL. Each worksheet
becomes one ``Page``: ``page.number`` is the workbook order (1-based) and
``page.name`` is the sheet title (``ws.title``). Every sheet is rendered
as a single Markdown pipe table via ``tabulate``, prefixed with an
``# {sheet_name}`` heading so the concatenated ``doc.text`` reads naturally.
"""
from _common import run


PROMPT = "Enter a .xlsx source (local path or http(s):// URL), or blank to quit."


if __name__ == "__main__":
    raise SystemExit(run(PROMPT))
