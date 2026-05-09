"""Interactive PDF reader example.

Usage:
    python examples/read_pdf.py

Prompts for a PDF source (a local path or an ``http(s)://`` URL), parses it
with ``fyle.open``, and prints a short summary plus a preview of the
Markdown text. This is the smallest end-to-end demo of the fyle API.

All interactive plumbing lives in ``examples/_common.py`` so every format's
script stays identical modulo its prompt line.
"""
from _common import run


PROMPT = "Enter a PDF source (local path or http(s):// URL), or blank to quit."


if __name__ == "__main__":
    raise SystemExit(run(PROMPT))
