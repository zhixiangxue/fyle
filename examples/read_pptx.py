"""Interactive PPTX reader example.

Usage:
    python examples/read_pptx.py

Accepts ``.pptx`` files, local path or ``http(s)://`` URL. Each slide
becomes one ``Page``: ``page.number`` is the 1-based slide index and
``page.name`` is the slide title (from the title placeholder). Text
frames, bullets, tables and embedded pictures are assembled into
Markdown, and structural elements are exposed through ``doc.tables`` /
``doc.images``.
"""
from _common import run


PROMPT = "Enter a .pptx source (local path or http(s):// URL), or blank to quit."


if __name__ == "__main__":
    raise SystemExit(run(PROMPT))
