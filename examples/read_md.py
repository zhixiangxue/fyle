"""Interactive Markdown reader example.

Usage:
    python examples/read_md.py

Accepts ``.md`` / ``.markdown`` files, local path or ``http(s)://`` URL.
The reader is a passthrough — the content is already our target
representation and is placed into ``doc.text`` unchanged.
"""
from _common import run


PROMPT = "Enter a .md / .markdown source (local path or http(s):// URL), or blank to quit."


if __name__ == "__main__":
    raise SystemExit(run(PROMPT))
