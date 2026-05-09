"""Image reader.

Multimodal LLMs (GPT-4o, Claude 3.5, Gemini, etc.) consume images via
base64 ``data:`` URLs or direct URLs. fyle therefore does the minimum
useful transformation: wrap the raw bytes into a ``data:`` URL and expose
them through both ``doc.text`` (as a Markdown image token) and
``doc.images`` so the caller can feed the document into a prompt directly.

fyle does not perform OCR. If you want text extracted from an image, run
an OCR / VLM pipeline on ``doc.images[0].data`` yourself.

File naming rule: ``stdlib.py`` \u2014 the core driver is Python's standard
library (``base64`` + ``mimetypes``). Pillow is optional and only used
for non-fatal metadata (dimensions), not for decoding.
"""
from __future__ import annotations

from . import stdlib  # noqa: F401
