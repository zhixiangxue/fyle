"""Interactive HTML reader example.

Usage:
    python examples/read_html.py

Accepts ``.html`` / ``.htm`` files, local path or ``http(s)://`` URL.
BeautifulSoup strips the ``<head>`` (and ``<script>`` / ``<style>`` blocks),
pulls ``<title>`` into ``doc.meta.title``, then ``markdownify`` converts the
body to Markdown with ATX-style headings (``# Heading``).
"""
from _common import run


PROMPT = "Enter an .html / .htm source (local path or http(s):// URL), or blank to quit."


if __name__ == "__main__":
    raise SystemExit(run(PROMPT))
