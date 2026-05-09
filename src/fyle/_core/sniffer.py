"""Format sniffer — three-path detection: extension + magic bytes + HTTP Content-Type.

Used by ``fyle.open`` to pick the right reader for a given input.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from ..errors import UnsupportedFormatError

# Plain-text-ish extensions. Everything here routes to the ``text`` format
# and is handled by the passthrough PlainTextReader. The list is intentionally
# broad: source code, structured data, config, logs and lightweight markup are
# all legitimate "feed this to an LLM" inputs for a file → LLM SDK.
#
# Excluded on purpose:
# - ``.md`` / ``.markdown`` / ``.html`` / ``.htm`` / ``.csv``: have dedicated
#   readers with structural extraction.
# - Binary / office formats (``.pdf`` / ``.docx`` / ``.xlsx`` / images / audio):
#   obviously not plain text.
_TEXT_EXTS: tuple[str, ...] = (
    # Generic plaintext
    ".txt", ".text", ".readme",
    # Python
    ".py", ".pyi", ".pyx", ".pyw",
    # JavaScript / TypeScript / web frontend sources
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    ".vue", ".svelte", ".astro",
    # Stylesheet sources (treated as plaintext — fyle is not a CSS parser)
    ".css", ".scss", ".sass", ".less", ".styl",
    # JVM family
    ".java", ".kt", ".kts", ".scala", ".sc", ".groovy",
    ".clj", ".cljs", ".cljc",
    # Systems / native
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".inl",
    ".m", ".mm", ".rs", ".go", ".swift", ".zig", ".d", ".nim",
    # .NET
    ".cs", ".fs", ".fsx", ".vb",
    # Dynamic / scripting
    ".rb", ".php", ".pl", ".pm", ".lua", ".dart",
    ".r", ".jl", ".hs", ".ml", ".mli",
    ".ex", ".exs", ".erl", ".hrl",
    ".elm", ".purs", ".cr", ".rkt",
    # Shell / batch
    ".sh", ".bash", ".zsh", ".fish", ".ksh",
    ".ps1", ".psm1", ".psd1", ".bat", ".cmd",
    # Structured data
    ".json", ".jsonl", ".ndjson", ".json5",
    ".yaml", ".yml",
    ".toml",
    ".xml", ".plist", ".rss", ".atom", ".svg",
    ".tsv",
    # Config / env
    ".ini", ".cfg", ".conf", ".properties", ".env",
    ".editorconfig", ".gitignore", ".gitattributes", ".dockerignore",
    ".npmrc", ".nvmrc", ".prettierrc", ".eslintrc", ".babelrc",
    # Build / lock
    ".mk", ".cmake", ".gradle", ".sbt", ".bazel", ".bzl",
    ".lock",
    # SQL / query
    ".sql", ".psql", ".cql", ".hql", ".sparql", ".graphql", ".gql",
    # Lightweight markup (beyond Markdown / HTML which have their own readers)
    ".rst", ".adoc", ".asciidoc", ".tex", ".bib", ".org", ".textile",
    # Templates / template-ish sources
    ".hbs", ".handlebars", ".mustache", ".njk", ".liquid",
    ".ejs", ".pug", ".jade", ".jinja", ".jinja2", ".j2", ".tmpl", ".tpl",
    # IDLs / schemas
    ".proto", ".thrift", ".avsc", ".capnp", ".fbs", ".smithy",
    # Diagrams / dev meta
    ".dot", ".mmd", ".puml", ".drawio",
    # Logs / diffs / patches
    ".log", ".diff", ".patch",
    # Misc
    ".resx",
)

# File extension -> format name.
_EXT_MAP: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
    ".db": "sqlite",
    ".sqlite": "sqlite",
    ".sqlite3": "sqlite",
    # Archive containers. The ``archive`` reader extracts to disk and
    # reports a Markdown listing; it deliberately does not parse contents.
    # Note: OOXML formats (.docx / .xlsx / .pptx) and SQLite databases are
    # technically ZIP-based or have their own magic; they are handled by
    # dedicated readers above and take precedence via extension.
    ".zip": "archive",
    ".tar": "archive",
    ".gz": "archive",
    ".tgz": "archive",
    ".bz2": "archive",
    ".tbz2": "archive",
    ".xz": "archive",
    ".txz": "archive",
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "html",
    ".htm": "html",
    ".csv": "csv",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".m4a": "audio",
    ".mp3": "audio",
    ".wav": "audio",
    ".mp4": "video",
    ".m4v": "video",
    ".mov": "video",
    ".avi": "video",
    ".mkv": "video",
    ".webm": "video",
    **{ext: "text" for ext in _TEXT_EXTS},
}

# HTTP Content-Type -> format name.
_MIME_MAP: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.sqlite3": "sqlite",
    "application/x-sqlite3": "sqlite",
    # Archive MIME types → archive reader (extract + list).
    "application/zip": "archive",
    "application/x-zip-compressed": "archive",
    "application/x-tar": "archive",
    "application/gzip": "archive",
    "application/x-gzip": "archive",
    "application/x-bzip2": "archive",
    "application/x-xz": "archive",
    "text/markdown": "markdown",
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/plain": "text",
    "text/csv": "csv",
    "application/csv": "csv",
    # Structured text data — treat as plaintext for LLM consumption.
    "application/json": "text",
    "application/ld+json": "text",
    "application/yaml": "text",
    "application/x-yaml": "text",
    "application/toml": "text",
    "application/xml": "text",
    "text/xml": "text",
    "image/svg+xml": "text",
    "application/javascript": "text",
    "text/javascript": "text",
    "application/typescript": "text",
    "application/x-sh": "text",
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
    "audio/mp4": "audio",
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "audio/x-wav": "audio",
    "video/mp4": "video",
    "video/quicktime": "video",
    "video/x-msvideo": "video",
    "video/x-matroska": "video",
    "video/webm": "video",
}


def _sniff_magic(data: bytes) -> Optional[str]:
    """Detect format from magic bytes. Covers the main v1 formats."""
    if len(data) == 0:
        return None
    if data.startswith(b"%PDF-"):
        return "pdf"
    # SQLite: the header is exactly "SQLite format 3\x00" (16 bytes).
    # Extensions like ``.db`` are ambiguous in the wild, so magic-byte
    # detection is the authoritative check.
    if data.startswith(b"SQLite format 3\x00"):
        return "sqlite"
    # PNG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    # JPEG
    if data.startswith(b"\xff\xd8\xff"):
        return "image"
    # WEBP: RIFF....WEBP
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image"
    # WAV: RIFF....WAVE
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WAVE":
        return "audio"
    # MP3: ID3 tag or MPEG frame header.
    if data.startswith(b"ID3"):
        return "audio"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "audio"
    # HTML: common opening tags.
    head = data[:256].lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        return "html"
    # OOXML / ZIP containers need extension or Content-Type to disambiguate;
    # return None so the caller falls back to the extension path.
    return None


def detect(
    src: Union[str, Path, bytes, bytearray],
    *,
    source_name: Optional[str] = None,
    content_type: Optional[str] = None,
) -> str:
    """Detect the format name.

    Detection priority:
    1. HTTP Content-Type (passed by the caller in URL mode).
    2. File extension from ``source_name`` or a string-valued ``src``.
    3. Magic bytes.

    Raises ``UnsupportedFormatError`` if all three paths fail.
    """
    fmt: Optional[str] = None

    # 1. Content-Type (preferred in URL mode).
    if content_type:
        mime = content_type.split(";", 1)[0].strip().lower()
        fmt = _MIME_MAP.get(mime)
        # Generic ``text/*`` fallback: any unrecognised ``text/*`` subtype
        # (e.g. ``text/x-python``, ``text/vnd.something``) routes to the
        # plaintext reader. Never downgrades a format we already mapped.
        if fmt is None and mime.startswith("text/"):
            fmt = "text"

    # 2. File extension.
    name = source_name
    if fmt is None and name is None and isinstance(src, (str, Path)):
        name = str(src)
    if fmt is None and name:
        ext = Path(name).suffix.lower()
        fmt = _EXT_MAP.get(ext)

    # 3. Magic bytes.
    if fmt is None and isinstance(src, (bytes, bytearray)):
        fmt = _sniff_magic(bytes(src[:512]))

    if fmt is None:
        raise UnsupportedFormatError(
            f"Cannot detect format (source_name={source_name!r}, content_type={content_type!r})"
        )
    return fmt
