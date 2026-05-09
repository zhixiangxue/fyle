"""Archive reader backed by Python's standard library (``zipfile`` / ``tarfile`` / ``gzip``).

Philosophy
----------
This reader does **one** thing: turn an archive file on disk into a
directory of extracted files, and report that outcome as Markdown.

It does **not**:

- recurse into inner archives,
- parse inner files (no ``fyle.open`` chaining),
- expose a Python fluent API like ``doc.file(path)`` or ``doc.extracted_to``.

The rationale is Unix-style tool composition: an LLM agent that needs the
contents of ``data/sales.csv`` inside ``archive.zip`` will read the text
(``Extracted to: .../archive/``), decide for itself, and issue a fresh
``fyle.open("archive/data/sales.csv")`` call. fyle is a file reader, not
a file-tree orchestrator.

Extraction location
-------------------
- When the source is a real local file, we extract **into the source's
  own directory**: ``~/Downloads/pack.zip`` → ``~/Downloads/pack/``.
- When the source is a URL / raw bytes / a file-like object without a
  path, we fall back to ``Path.cwd()``.
- If the destination directory already exists, we append ``-2`` / ``-3``
  / ... until we find a free name. We never overwrite, never merge.

Safety
------
Two CVE-grade defences always apply:

1. **Path traversal**: every archive member's resolved absolute path
   must remain inside the destination directory. Escapees are dropped
   with a warning.
2. **Symlinks**: tar archives can ship symlinks; we refuse to create
   any symlink entry and instead record a warning. Zip has no native
   symlink representation so this only applies to tar.

Everything else the user may fear (zip bombs, .exe members, nested
archives, 10 GB files) is deliberately *not* policed here. The caller
has the final say — fyle does not decide what files are "safe" to
unpack.

File naming rule: ``stdlib.py`` — powered by Python's ``zipfile``,
``tarfile`` and ``gzip`` modules; no third-party dependency.
"""
from __future__ import annotations

import gzip
import io
import os
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from ..base import Reader
from ..._core.document import Document, Meta, Page
from ...errors import ParseError


# Recognised compound extensions (two-segment) that the archive reader
# should collapse when deriving the destination directory name.
# ``data.tar.gz`` → ``data`` (strip both segments), not ``data.tar``.
_COMPOUND_SUFFIXES = (
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".tgz",
    ".tbz2",
    ".txz",
)


class ArchiveEntry:
    """Lightweight record of one extracted member (purely for listing)."""

    __slots__ = ("path", "size", "modified", "kind")

    def __init__(
        self,
        path: str,
        size: int,
        modified: Optional[datetime],
        kind: str,
    ) -> None:
        self.path = path
        self.size = size
        self.modified = modified
        self.kind = kind  # "file" | "dir"


class ArchiveReader(Reader):
    name = "archive-stdlib"
    formats = ("archive",)
    is_default = True

    def read(
        self,
        data: bytes,
        *,
        source_name: Optional[str] = None,
        source_path: Optional[str] = None,
        **_,
    ) -> Document:
        if not data:
            raise ParseError("archive-stdlib reader: input is empty")

        warnings: list[str] = []
        kind = _detect_kind(data, source_name)
        if kind is None:
            raise ParseError(
                "archive-stdlib reader: could not detect archive type "
                f"(source_name={source_name!r})"
            )

        # Decide destination directory: same dir as source file, else cwd.
        dest_parent = _destination_parent(source_path)
        base_name = _base_name_from_source(source_name, kind)
        dest_dir = _unique_dir(dest_parent / base_name)
        dest_dir.mkdir(parents=True, exist_ok=False)

        # Extract.
        try:
            if kind == "zip":
                entries = _extract_zip(data, dest_dir, warnings)
            elif kind == "tar":
                entries = _extract_tar(data, dest_dir, mode="r:*", warnings=warnings)
            elif kind == "gz-single":
                entries = _extract_gzip_single(data, dest_dir, source_name, warnings)
            else:  # pragma: no cover - defensive
                raise ParseError(f"archive-stdlib reader: unhandled kind {kind!r}")
        except ParseError:
            raise
        except Exception as e:
            raise ParseError(f"archive-stdlib reader: extraction failed: {e}") from e

        # Build the Markdown report.
        md = _render_report(
            archive_name=source_name or "(unnamed archive)",
            dest_dir=dest_dir,
            entries=entries,
        )
        page = Page(text=md, number=1)

        # Pick a stable, human-friendly ext for ``meta.ext``. The dispatcher
        # would otherwise fill in just the last suffix (e.g. ``gz`` for
        # ``.tar.gz``), which hides the real shape of the file.
        ext = _canonical_ext(source_name)

        meta = Meta(
            format="archive",
            ext=ext,
            pages=1,
            size=len(data),
            title=Path(source_name).stem if source_name else None,
            reader=self.name,
            created_at=datetime.now(timezone.utc),
            warnings=warnings,
        )
        return Document(pages=[page], meta=meta)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _detect_kind(data: bytes, source_name: Optional[str]) -> Optional[str]:
    """Return ``"zip"`` / ``"tar"`` / ``"gz-single"`` or ``None``.

    We prefer magic bytes, then fall back to extension. ``gz-single`` means
    a bare gzip wrapping a single non-tar payload (``.gz`` without ``.tar``).
    """
    # ZIP magic.
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"

    # Uncompressed tar: offset 257 holds "ustar".
    if len(data) >= 263 and data[257:262] in (b"ustar", b"ustar\x00"):
        return "tar"

    # Gzipped payload. Could be ``.tar.gz`` or a standalone ``.gz``.
    if data.startswith(b"\x1f\x8b"):
        name = (source_name or "").lower()
        if name.endswith((".tar.gz", ".tgz")):
            return "tar"
        # Try treating as tar.gz first (many tar.gz files are named .gz
        # in the wild); fall back to single-file gzip on failure.
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz"):
                return "tar"
        except (tarfile.TarError, OSError):
            return "gz-single"

    # Bzip2.
    if data.startswith(b"BZh"):
        name = (source_name or "").lower()
        if name.endswith((".tar.bz2", ".tbz2")):
            return "tar"
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:bz2"):
                return "tar"
        except (tarfile.TarError, OSError):
            return None

    # xz.
    if data.startswith(b"\xfd7zXZ\x00"):
        name = (source_name or "").lower()
        if name.endswith((".tar.xz", ".txz")):
            return "tar"
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz"):
                return "tar"
        except (tarfile.TarError, OSError):
            return None

    # Extension-only fallbacks (rare: e.g. empty / truncated archives).
    name = (source_name or "").lower()
    if name.endswith(".zip"):
        return "zip"
    if name.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
        return "tar"
    if name.endswith(".gz"):
        return "gz-single"
    return None


def _destination_parent(source_path: Optional[str]) -> Path:
    """Where to place the extracted directory.

    Local files extract into their own directory; URLs / bytes extract
    into the current working directory.
    """
    if source_path:
        try:
            p = Path(source_path).resolve()
            if p.is_file():
                return p.parent
        except OSError:
            pass
    return Path.cwd()


def _base_name_from_source(source_name: Optional[str], kind: str) -> str:
    """Derive the extracted directory's base name (no path, no extension).

    Compound suffixes like ``.tar.gz`` are stripped in one go so
    ``data.tar.gz`` becomes ``data`` rather than ``data.tar``.
    """
    if not source_name:
        return "fyle-archive" if kind != "gz-single" else "fyle-gzip"
    lower = source_name.lower()
    for suf in _COMPOUND_SUFFIXES:
        if lower.endswith(suf):
            return source_name[: -len(suf)] or "fyle-archive"
    return Path(source_name).stem or "fyle-archive"


def _unique_dir(candidate: Path) -> Path:
    """Return ``candidate`` if free, otherwise append ``-2`` / ``-3`` / ..."""
    if not candidate.exists():
        return candidate
    for i in range(2, 10_000):
        alt = candidate.with_name(f"{candidate.name}-{i}")
        if not alt.exists():
            return alt
    raise ParseError(
        f"archive-stdlib reader: could not find a free destination near {candidate}"
    )


def _canonical_ext(source_name: Optional[str]) -> Optional[str]:
    """Return a user-facing ext string (``zip`` / ``tar.gz`` / ...)."""
    if not source_name:
        return None
    lower = source_name.lower()
    for suf in _COMPOUND_SUFFIXES:
        if lower.endswith(suf):
            return suf.lstrip(".")
    return Path(lower).suffix.lstrip(".") or None


def _is_inside(dest: Path, candidate: Path) -> bool:
    """True iff ``candidate`` (resolved) is inside ``dest`` (resolved)."""
    try:
        candidate.resolve().relative_to(dest.resolve())
        return True
    except (ValueError, OSError):
        return False


def _safe_join(dest: Path, member_name: str) -> Optional[Path]:
    """Join ``dest`` and ``member_name``, rejecting traversal attempts."""
    # Normalise leading slashes and drive letters; treat as relative.
    clean = member_name.replace("\\", "/").lstrip("/")
    if not clean:
        return None
    target = (dest / clean).resolve()
    if not _is_inside(dest, target):
        return None
    return target


# ----------------------------------------------------------------------
# Extractors
# ----------------------------------------------------------------------

def _extract_zip(
    data: bytes,
    dest: Path,
    warnings: list[str],
) -> list[ArchiveEntry]:
    entries: list[ArchiveEntry] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            target = _safe_join(dest, info.filename)
            if target is None:
                warnings.append(f"archive: skipped path traversal entry {info.filename!r}")
                continue

            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                entries.append(
                    ArchiveEntry(
                        path=_relative(target, dest),
                        size=0,
                        modified=_zip_mtime(info),
                        kind="dir",
                    )
                )
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, open(target, "wb") as out:
                _copy_stream(src, out)
            entries.append(
                ArchiveEntry(
                    path=_relative(target, dest),
                    size=info.file_size,
                    modified=_zip_mtime(info),
                    kind="file",
                )
            )
    return entries


def _extract_tar(
    data: bytes,
    dest: Path,
    *,
    mode: str,
    warnings: list[str],
) -> list[ArchiveEntry]:
    entries: list[ArchiveEntry] = []
    with tarfile.open(fileobj=io.BytesIO(data), mode=mode) as tf:
        for member in tf.getmembers():
            if member.issym() or member.islnk():
                warnings.append(
                    f"archive: skipped symlink/hardlink entry {member.name!r}"
                )
                continue
            if member.isdev() or member.isfifo():
                warnings.append(f"archive: skipped device/fifo entry {member.name!r}")
                continue

            target = _safe_join(dest, member.name)
            if target is None:
                warnings.append(f"archive: skipped path traversal entry {member.name!r}")
                continue

            mtime = (
                datetime.fromtimestamp(member.mtime, tz=timezone.utc)
                if member.mtime
                else None
            )

            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                entries.append(
                    ArchiveEntry(
                        path=_relative(target, dest),
                        size=0,
                        modified=mtime,
                        kind="dir",
                    )
                )
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            f = tf.extractfile(member)
            if f is None:
                warnings.append(f"archive: unreadable entry {member.name!r}")
                continue
            try:
                with open(target, "wb") as out:
                    _copy_stream(f, out)
            finally:
                f.close()
            entries.append(
                ArchiveEntry(
                    path=_relative(target, dest),
                    size=member.size,
                    modified=mtime,
                    kind="file",
                )
            )
    return entries


def _extract_gzip_single(
    data: bytes,
    dest: Path,
    source_name: Optional[str],
    warnings: list[str],
) -> list[ArchiveEntry]:
    """Decompress a standalone ``.gz`` (not ``.tar.gz``) into one file."""
    # Pick the inner filename. ``payload.gz`` → ``payload``.
    inner_name = (
        source_name[:-3] if source_name and source_name.lower().endswith(".gz")
        else "payload"
    )
    inner_name = Path(inner_name).name or "payload"
    target = dest / inner_name
    with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as gz:
        payload = gz.read()
    target.write_bytes(payload)
    return [
        ArchiveEntry(
            path=_relative(target, dest),
            size=len(payload),
            modified=None,
            kind="file",
        )
    ]


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------

def _render_report(
    archive_name: str,
    dest_dir: Path,
    entries: list[ArchiveEntry],
) -> str:
    files = [e for e in entries if e.kind == "file"]
    dirs = [e for e in entries if e.kind == "dir"]
    total_size = sum(e.size for e in files)

    lines: list[str] = [
        f"# Archive: {archive_name}",
        "",
        f"Extracted to: `{dest_dir}`",
        "",
        f"## Contents ({len(files)} files, {len(dirs)} dirs, "
        f"{_format_bytes(total_size)} total)",
        "",
    ]

    if not entries:
        lines.append("_(archive contained no extractable entries)_")
        return "\n".join(lines)

    # Sort by path for stable, diff-friendly output.
    entries_sorted = sorted(entries, key=lambda e: e.path)
    lines.append("| path | size | modified |")
    lines.append("|---|---|---|")
    for e in entries_sorted:
        path = e.path + ("/" if e.kind == "dir" and not e.path.endswith("/") else "")
        size = "-" if e.kind == "dir" else _format_bytes(e.size)
        mtime = e.modified.strftime("%Y-%m-%d %H:%M") if e.modified else "-"
        lines.append(f"| {_md_escape(path)} | {size} | {mtime} |")

    return "\n".join(lines)


def _format_bytes(n: int) -> str:
    if n >= 1024 * 1024 * 1024:
        return f"{n / (1024 ** 3):.2f} GB"
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def _relative(target: Path, base: Path) -> str:
    try:
        return target.resolve().relative_to(base.resolve()).as_posix()
    except (ValueError, OSError):
        return target.as_posix()


def _zip_mtime(info: zipfile.ZipInfo) -> Optional[datetime]:
    try:
        # ZipInfo.date_time is naive; treat as local time.
        return datetime(*info.date_time)
    except (ValueError, TypeError):
        return None


def _copy_stream(src, dst, chunk: int = 1024 * 1024) -> None:
    while True:
        buf = src.read(chunk)
        if not buf:
            break
        dst.write(buf)
