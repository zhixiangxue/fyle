"""Minimal universal reader example — ``fyle.read()`` in one line.

Usage::

    python examples/read_any.py

Prompts for any supported source (local path or ``http(s)://`` URL),
calls :func:`fyle.read` on it, and prints the result verbatim — the
exact LLM-ready string you would hand to a model. No summary, no
preview, no truncation.

This is the smallest possible demo of what fyle is for: one function
in, one string out, ready to feed to an LLM.
"""
from __future__ import annotations

import sys

from _common import _normalize_source

import fyle


PROMPT = (
    "Enter any supported source (PDF / DOCX / XLSX / image / audio / "
    "video / code / config / ... — local path or http(s):// URL), or "
    "blank to quit.\n"
    "Tip: you can drag a file from Finder into the terminal.\n"
    "> "
)


def main() -> int:
    try:
        raw = input(PROMPT)
    except (EOFError, KeyboardInterrupt):
        print()
        return 0

    src = _normalize_source(raw)
    if not src:
        print("No source given. Bye.")
        return 0

    try:
        print(fyle.read(src))
    except fyle.DownloadError as e:
        print(f"[DownloadError] {e}", file=sys.stderr)
        return 1
    except fyle.UnsupportedFormatError as e:
        print(f"[UnsupportedFormatError] {e}", file=sys.stderr)
        return 1
    except fyle.ReaderNotFoundError as e:
        print(
            f"[ReaderNotFoundError] {e}\nAvailable readers: {fyle.readers()}",
            file=sys.stderr,
        )
        return 1
    except fyle.ParseError as e:
        print(f"[ParseError] {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"[FileNotFoundError] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
