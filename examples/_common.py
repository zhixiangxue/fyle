"""Shared helpers for the ``examples/read_*.py`` scripts.

Each ``read_<format>.py`` is just a thin wrapper over ``run(prompt_header)``
here — this file owns the interactive loop, error reporting, and summary
printing so the format-specific scripts stay short and obviously
equivalent.

The script directory (``examples/``) is added to ``sys.path`` automatically
by Python when a script is run directly (``python examples/read_xxx.py``),
so the ``from _common import run`` import in sibling scripts works out of
the box.
"""
from __future__ import annotations

import sys
import textwrap
from urllib.parse import unquote, urlparse

import fyle


PREVIEW_CHARS = 800  # How much of doc.text to print as a preview.
MAX_TABLES_SHOWN = 3  # At most this many tables get a header/row preview.
MAX_IMAGES_SHOWN = 10  # At most this many images get a src/caption preview.
TABLE_PREVIEW_LINES = 6  # At most this many lines per table.text preview.
IMG_SRC_PREVIEW = 100  # Truncate image src past this many chars.
IMG_CAPTION_PREVIEW = 40  # Truncate image caption past this many chars.


def _normalize_source(raw: str) -> str:
    """Clean up common shell-drag artifacts in a user-entered path or URL.

    When a file is dragged into a terminal, the shell (zsh / bash) often wraps
    the path in matching single or double quotes, or backslash-escapes spaces
    and special characters. macOS Finder may also hand over a ``file://`` URL.
    We undo all three so the user can just drag-and-drop without thinking.
    """
    s = raw.strip()

    # 1. Matching surrounding quotes added by the shell.
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1]

    # 2. ``file://`` URL (Finder drag on macOS).
    if s.startswith("file://"):
        return unquote(urlparse(s).path)

    # 3. zsh backslash-escaped spaces / parens / ampersands in local paths.
    #    Don't touch http(s) URLs — backslashes are not valid there anyway.
    if not s.startswith(("http://", "https://")):
        for esc, plain in (("\\ ", " "), ("\\(", "("), ("\\)", ")"), ("\\&", "&")):
            s = s.replace(esc, plain)

    return s


def _prompt_source(prompt_header: str) -> str:
    """Ask the user for a file source. Returns a cleaned, possibly empty string."""
    prompt = (
        f"{prompt_header}\n"
        "Tip: you can drag a file from Finder into the terminal.\n"
        "> "
    )
    try:
        raw = input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()  # newline after ^C / ^D
        return ""
    return _normalize_source(raw)


def _format_bytes(n: int) -> str:
    """Human-readable byte size (KB / MB)."""
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _print_summary(doc: fyle.Document) -> None:
    meta = doc.meta
    print()
    print("=" * 60)
    print("  Document summary")
    print("=" * 60)
    print(f"  reader    : {meta.reader}")
    print(f"  format    : {meta.format}")
    print(f"  ext       : {meta.ext or '-'}")
    print(f"  pages     : {meta.pages}")
    print(f"  size      : {_format_bytes(meta.size)}")
    print(f"  title     : {meta.title or '-'}")
    print(f"  author    : {meta.author or '-'}")
    print(f"  created   : {meta.created_at.isoformat() if meta.created_at else '-'}")
    print(f"  tables    : {len(doc.tables)}")
    print(f"  images    : {len(doc.images)}")
    print(f"  tokens    : {doc.tokens}")
    # Show page names when any page has one (xlsx sheets, future pptx slides).
    named = [(p.number, p.name) for p in doc.pages if p.name]
    if named:
        print(f"  page names: {named}")
    if meta.warnings:
        print(f"  warnings  : {len(meta.warnings)}")
        for w in meta.warnings:
            print(f"    - {w}")

    _print_tables(doc)
    _print_images(doc)

    print()
    print("-" * 60)
    print("  Markdown preview (first %d chars)" % PREVIEW_CHARS)
    print("-" * 60)
    preview = doc.text[:PREVIEW_CHARS]
    if len(doc.text) > PREVIEW_CHARS:
        preview += f"\n\n... (+{len(doc.text) - PREVIEW_CHARS} more chars)"
    print(textwrap.indent(preview, "  "))
    print()


def _print_tables(doc: fyle.Document) -> None:
    """Print a short preview of each extracted table so the caller can see
    that structural extraction actually produced the expected shape."""
    tables = doc.tables
    if not tables:
        return
    print()
    print("-" * 60)
    print(f"  Tables ({len(tables)} total, showing up to {MAX_TABLES_SHOWN})")
    print("-" * 60)
    for i, t in enumerate(tables[:MAX_TABLES_SHOWN], start=1):
        print(f"  [table #{i}] page={t.page} headers={t.headers}")
        print(f"             rows={len(t.rows)} first_row={t.rows[0] if t.rows else None}")
        if t.text:
            snippet_lines = t.text.splitlines()[:TABLE_PREVIEW_LINES]
            for line in snippet_lines:
                print(f"    | {line}")
            if len(t.text.splitlines()) > TABLE_PREVIEW_LINES:
                print(f"    | ... (+{len(t.text.splitlines()) - TABLE_PREVIEW_LINES} more lines)")
        print()
    if len(tables) > MAX_TABLES_SHOWN:
        print(f"  ... (+{len(tables) - MAX_TABLES_SHOWN} more tables)")


def _print_images(doc: fyle.Document) -> None:
    """Print a short preview of each extracted image (src + caption only).
    We never fetch or decode image bytes here; the reader's job is to
    surface references, not download them."""
    images = doc.images
    if not images:
        return
    print()
    print("-" * 60)
    print(f"  Images ({len(images)} total, showing up to {MAX_IMAGES_SHOWN})")
    print("-" * 60)
    for i, img in enumerate(images[:MAX_IMAGES_SHOWN], start=1):
        src = img.data_url or ""
        if src.startswith("data:"):
            src_display = src[:30] + f"... ({len(src)} chars)"
        elif len(src) > IMG_SRC_PREVIEW:
            src_display = src[:IMG_SRC_PREVIEW] + "..."
        else:
            src_display = src
        caption = (img.caption or "").strip()
        if len(caption) > IMG_CAPTION_PREVIEW:
            caption = caption[:IMG_CAPTION_PREVIEW] + "..."
        print(f"  [img #{i}] page={img.page}")
        print(f"           src     : {src_display}")
        print(f"           caption : {caption or '-'}")
    if len(images) > MAX_IMAGES_SHOWN:
        print(f"  ... (+{len(images) - MAX_IMAGES_SHOWN} more images)")


def run(prompt_header: str) -> int:
    """Run the interactive read-and-summarise loop once and return an exit code."""
    src = _prompt_source(prompt_header)
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
        print(f"[UnsupportedFormatError] fyle does not support this format: {e}", file=sys.stderr)
        return 1
    except fyle.ReaderNotFoundError as e:
        print(
            f"[ReaderNotFoundError] no reader available for this format: {e}\n"
            f"Available readers: {fyle.readers()}",
            file=sys.stderr,
        )
        return 1
    except fyle.ParseError as e:
        print(f"[ParseError] the file could not be parsed: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(
            f"[FileNotFoundError] {e}\n"
            "Hint: if you dragged a file into the terminal, the shell may have "
            "wrapped it in quotes — this script already strips them, but check "
            "for stray characters.",
            file=sys.stderr,
        )
        return 1

    _print_summary(doc)
    return 0
