"""Interactive archive reader example.

Usage:
    python examples/read_archive.py

Accepts ``.zip`` / ``.tar`` / ``.tar.gz`` / ``.tgz`` / ``.tar.bz2`` /
``.tbz2`` / ``.tar.xz`` / ``.txz`` / ``.gz`` files, local path or
``http(s)://`` URL.

What the archive reader does (and does not)
-------------------------------------------
The reader extracts the archive to disk and hands back a single
Markdown page that lists: where it extracted to, plus each member's
path, size and modified time. That is the whole API — there is no
``doc.file(name)``, no ``doc.extracted_to`` attribute, no recursive
reading of inner archives. Think of it as a Unix-style shell tool:
an LLM agent reads the listing, decides which inner file it wants,
then issues a fresh ``fyle.open("<extracted-dir>/inner.csv")`` call.

Extraction location
-------------------
Local source files extract **into the source's own directory**, e.g.
``~/Downloads/pack.zip`` → ``~/Downloads/pack/``. URL / bytes
sources extract into the current working directory. If the
destination already exists, a ``-2`` / ``-3`` / ... suffix is
appended — we never overwrite existing files.

Safety red lines
----------------
- Path-traversal entries (``../../etc/passwd``) are dropped.
- Tar symlinks / hardlinks / device / fifo entries are dropped.
Every skip is recorded in ``doc.meta.warnings`` — read the summary
to see what the archive tried to pull.
"""
from _common import run


PROMPT = (
    "Enter an archive source "
    "(.zip / .tar / .tar.gz / .tgz / .tar.bz2 / .tar.xz / .gz — local path or http(s):// URL), "
    "or blank to quit."
)


if __name__ == "__main__":
    raise SystemExit(run(PROMPT))
