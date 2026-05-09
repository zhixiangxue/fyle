"""Token estimation and paragraph-boundary chunking.

- Token estimation: prefer ``tiktoken`` with the ``cl100k_base`` encoding;
  fall back to ~4 chars/token when tiktoken is unavailable.
- Chunking: aggregate paragraphs (split on ``\n\n``) under a ``max_tokens``
  soft limit; fill ``overlap`` by back-filling whole trailing paragraphs.
"""
from __future__ import annotations

from typing import Iterator, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .document import Chunk, Document

_ENCODING: object = None  # tiktoken Encoding instance or the string "fallback".


def _get_encoding():
    global _ENCODING
    if _ENCODING is None:
        try:
            import tiktoken

            _ENCODING = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENCODING = "fallback"
    return _ENCODING


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text``."""
    if not text:
        return 0
    enc = _get_encoding()
    if enc == "fallback":
        return max(1, len(text) // 4)
    return len(enc.encode(text))


def chunk_document(
    doc: "Document", *, max_tokens: int = 4000, overlap: int = 200
) -> Iterator["Chunk"]:
    """Split a ``Document`` on paragraph boundaries.

    - No hard cuts: if adding the next paragraph would overflow ``max_tokens``,
      yield the current chunk first.
    - ``overlap``: back-fill trailing paragraphs of the just-yielded chunk
      until the accumulated overlap reaches roughly ``overlap`` tokens.
    - ``page_range``: derived from the source page numbers of the paragraphs
      in the chunk; ``None`` for formats without native pagination.
    """
    from .document import Chunk

    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= max_tokens:
        raise ValueError("overlap must be smaller than max_tokens")

    # 1. Split every page.text into paragraphs, tagged with their source page number.
    paragraphs: list[tuple[str, Optional[int]]] = []
    for page in doc.pages:
        page_num = page.number
        for para in page.text.split("\n\n"):
            para = para.strip()
            if para:
                paragraphs.append((para, page_num))

    if not paragraphs:
        return

    buf: list[str] = []
    buf_pages: list[Optional[int]] = []
    buf_tokens: int = 0

    def make_chunk() -> Chunk:
        text = "\n\n".join(buf)
        real_pages = [p for p in buf_pages if p is not None]
        page_range: Optional[tuple[int, int]] = (
            (min(real_pages), max(real_pages)) if real_pages else None
        )
        return Chunk(text=text, tokens=estimate_tokens(text), page_range=page_range)

    for para, page_num in paragraphs:
        p_tokens = estimate_tokens(para)
        if buf and buf_tokens + p_tokens > max_tokens:
            yield make_chunk()
            # Back-fill overlap from the tail of the previous buffer.
            carry: list[str] = []
            carry_pages: list[Optional[int]] = []
            carry_tokens = 0
            if overlap > 0:
                for prev_para, prev_page in zip(reversed(buf), reversed(buf_pages)):
                    t = estimate_tokens(prev_para)
                    if carry_tokens + t > overlap:
                        break
                    carry.insert(0, prev_para)
                    carry_pages.insert(0, prev_page)
                    carry_tokens += t
            buf, buf_pages, buf_tokens = carry, carry_pages, carry_tokens
        buf.append(para)
        buf_pages.append(page_num)
        buf_tokens += p_tokens

    if buf:
        yield make_chunk()
