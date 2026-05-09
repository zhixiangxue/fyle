"""Interactive DOCX reader example.

Usage:
    python examples/read_docx.py

Accepts ``.docx`` files, local path or ``http(s)://`` URL. Parsing uses
the two-stage pipeline ``mammoth`` → HTML → ``markdownify``, which renders
Word tables as proper Markdown pipe tables (``mammoth`` 's direct Markdown
target tends to degrade tables into one-paragraph-per-cell). Inline images
embedded in the document are harvested into ``doc.images``.

DOCX has no native pagination, so ``doc.pages`` contains a single ``Page``.
"""
from _common import run


PROMPT = "Enter a .docx source (local path or http(s):// URL), or blank to quit."


if __name__ == "__main__":
    raise SystemExit(run(PROMPT))
