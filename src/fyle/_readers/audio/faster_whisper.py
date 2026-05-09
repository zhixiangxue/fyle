"""Audio reader backed by ``faster-whisper``.

Produces a ``Document`` whose ``doc.text`` is the time-stamped Markdown
transcript of the input audio. One ``Page`` per file; per-segment
timestamps (``[MM:SS]``) are inlined so the LLM can cite moments.

Why this file exists
--------------------
Transcription is the only credible way to turn audio into something an
LLM "sees". Whisper is the only open-source ASR model with broad
multilingual coverage that is practical on a CPU; ``faster-whisper``
(CTranslate2 int8) is the fastest Python binding and avoids the
PyTorch dependency chain. See ``.._whisper`` for the shared model cache
and transcript formatter.

Source-path vs bytes
--------------------
faster-whisper decodes audio via PyAV, which is happiest with a real
filesystem path. We write the bytes to a NamedTemporaryFile with the
right suffix (important: PyAV sometimes sniffs the container from the
extension), transcribe, then delete. The temp file is **not** the
input file itself even when a local ``source_path`` is available —
keeping a single code path simplifies URL / bytes / file-like inputs.

File naming rule: ``faster_whisper.py`` — the core driver library.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .. import _whisper
from ..base import Reader
from ..._core.document import Document, Meta, Page
from ...errors import ParseError


class FasterWhisperAudioReader(Reader):
    name = "faster-whisper"
    formats = ("audio",)
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
            raise ParseError("faster-whisper reader: input is empty")

        # Preserve the suffix so PyAV can sniff the container correctly.
        # ``.mp3`` vs ``.m4a`` share different demuxers; a mislabelled
        # suffix occasionally trips PyAV's probing.
        suffix = _pick_suffix(source_name)
        warnings: list[str] = []

        tmp = tempfile.NamedTemporaryFile(
            prefix="fyle-audio-",
            suffix=suffix,
            delete=False,
        )
        try:
            tmp.write(data)
            tmp.close()
            try:
                segments, info = _whisper.transcribe(tmp.name)
            except Exception as e:
                raise ParseError(
                    f"faster-whisper reader: transcription failed: {e}"
                ) from e
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        text = _render_page_text(
            source_name=source_name,
            duration_sec=float(info.get("duration", 0.0) or 0.0),
            language=info.get("language"),
            segments=segments,
        )

        # Record what the model heard: language + duration + model size.
        # These go into meta.warnings so they surface in the example's
        # summary without polluting the content surface.
        if info.get("language"):
            warnings.append(
                f"detected language: {info['language']} "
                f"(p={info.get('language_probability', 0):.2f})"
            )
        if info.get("duration"):
            warnings.append(
                f"audio duration: {_whisper.format_timestamp(info['duration'])}"
            )
        warnings.append(f"whisper model: {_whisper.model_size()}")

        title = Path(source_name).stem if source_name else None
        page = Page(text=text, number=1)
        meta = Meta(
            format="audio",
            pages=1,
            size=len(data),
            title=title,
            reader=self.name,
            created_at=datetime.now(timezone.utc),
            warnings=warnings,
        )
        return Document(pages=[page], meta=meta)


_KNOWN_AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac"}


def _render_page_text(
    *,
    source_name: Optional[str],
    duration_sec: float,
    language: Optional[str],
    segments: list[dict],
) -> str:
    """Render the audio page as Markdown with a lightweight header.

    Header mirrors the video reader (Duration + Language) so callers that
    feed ``doc.text`` into an LLM without ``doc.meta`` still see the core
    context up front. Kept minimal on purpose: model size / confidence go
    into ``meta.warnings`` rather than the content surface.
    """
    title = source_name or "(unnamed audio)"
    dur = _whisper.format_timestamp(duration_sec) if duration_sec else "-"
    lang = language or "-"
    transcript = _whisper.format_transcript(segments)
    return (
        f"# Audio: {title}\n"
        "\n"
        f"- Duration: `{dur}`\n"
        f"- Language: `{lang}`\n"
        "\n"
        "## Transcript\n"
        "\n"
        f"{transcript}"
    )


def _pick_suffix(source_name: Optional[str]) -> str:
    """Return a file suffix that helps PyAV sniff the container.

    Falls back to ``.wav`` (safest generic guess) when the caller cannot
    supply a name; PyAV will still probe magic bytes but a plausible
    extension keeps some demuxers honest.
    """
    if source_name:
        ext = Path(source_name).suffix.lower()
        if ext in _KNOWN_AUDIO_SUFFIXES:
            return ext
    return ".wav"
