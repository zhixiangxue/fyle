"""Image reader implementation backed by the Python standard library.

Strategy:
- Detect the concrete image subtype (png / jpeg / webp / ...) from magic
  bytes or the file extension.
- Wrap the raw bytes as a ``data:<mime>;base64,<payload>`` URL.
- Expose the image both as an ``Image`` element and as a Markdown image
  token in ``Page.text`` so the document can be fed directly into a
  multimodal LLM prompt.
- Optionally record pixel dimensions in ``meta.warnings`` if Pillow is
  available; failure to read dimensions never fails the parse.

Why no OCR here: fyle's contract is "open anything, return Markdown".
OCR / VLM calls are an application-level choice (network, cost, model
selection) and are deliberately kept out of the reader layer.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..base import Reader
from ..._core.document import Document, Image, Meta, Page
from ...errors import ParseError


# Magic-byte prefixes that pin down the concrete image subtype. Order
# matters: WEBP also starts with ``RIFF``, so it is checked after the
# RIFF-aware case below.
_MAGIC_MIME: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    # TIFF little / big endian
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
]

# Fallback extension -> MIME if magic-byte detection missed.
_EXT_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}


def _detect_mime(data: bytes, source_name: Optional[str]) -> str:
    """Return the best-guess ``image/*`` MIME for ``data``.

    Falls back to ``application/octet-stream`` only if nothing matches;
    callers receive a usable data URL either way.
    """
    # WEBP: ``RIFF....WEBP`` (4-byte size between RIFF and WEBP).
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    for prefix, mime in _MAGIC_MIME:
        if data.startswith(prefix):
            return mime
    if source_name:
        ext = Path(source_name).suffix.lower()
        if ext in _EXT_MIME:
            return _EXT_MIME[ext]
    return "application/octet-stream"


def _try_dimensions(data: bytes, warnings: list[str]) -> Optional[tuple[int, int]]:
    """Best-effort (width, height) via Pillow. Never raises on failure."""
    try:
        from PIL import Image as _PILImage
    except ImportError:
        return None
    try:
        import io as _io
        with _PILImage.open(_io.BytesIO(data)) as im:
            return int(im.width), int(im.height)
    except Exception as e:
        warnings.append(f"image dimension read failed: {e}")
        return None


class ImageReader(Reader):
    name = "image-stdlib"
    formats = ("image",)
    is_default = True

    def read(self, data: bytes, *, source_name: Optional[str] = None, **_) -> Document:
        if not data:
            raise ParseError("image-stdlib reader: input is empty")

        warnings: list[str] = []

        mime = _detect_mime(data, source_name)
        b64 = base64.b64encode(data).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"

        # Caption / title: filename stem if available, else the format name.
        stem: Optional[str] = None
        if source_name:
            try:
                stem = Path(source_name).stem or None
            except (TypeError, ValueError):
                stem = None
        caption = stem or mime.split("/", 1)[-1]

        dims = _try_dimensions(data, warnings)
        if dims is not None:
            warnings.append(f"image dimensions: {dims[0]}x{dims[1]}")

        # Markdown image token. LLM prompts can consume this verbatim.
        page_text = f"![{caption}]({data_url})"

        image = Image(data_url=data_url, data=data, caption=caption, page=1)

        try:
            page = Page(text=page_text, number=1, images=[image])
            meta = Meta(
                format="image",
                pages=1,
                size=len(data),
                title=stem,
                reader=self.name,
                created_at=datetime.now(timezone.utc),
                warnings=warnings,
            )
            return Document(pages=[page], meta=meta)
        except Exception as e:  # pragma: no cover - defensive
            raise ParseError(f"image reader failed to build Document: {e}") from e
