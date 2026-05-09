"""Shared Whisper-transcription helpers used by the audio and video readers.

Both readers transcribe audio through ``faster-whisper``. Keeping the
model-loading and transcript-formatting logic here avoids two almost
identical copies and ensures the same model instance can be reused
across calls within a single process.

Design notes
------------
- **Backend**: ``faster-whisper`` on CPU with int8 quantisation. CPU +
  int8 is ~4x faster than the original openai-whisper on a typical
  laptop, while keeping the total install footprint (CTranslate2 wheel
  + PyAV + onnxruntime) around 90 MB. No PyTorch, no CUDA assumption.
- **Model**: hard-coded to ``base`` (~140 MB). Small enough to download
  in under a minute on residential broadband, accurate enough for most
  spoken content including Chinese and English. Developers who need a
  different size can override via the ``FYLE_WHISPER_MODEL`` env var.
- **Caching**: delegated to faster-whisper / huggingface_hub, which
  stores model weights under ``~/.cache/huggingface/hub/``. First call
  triggers a one-time download; subsequent calls are fully offline.
- **Lazy import**: ``faster_whisper`` is imported inside the helper
  functions, not at module top. This lets ``import fyle`` succeed in
  environments that installed the base package without the ``audio`` /
  ``video`` extras; the informative ImportError surfaces only when the
  user actually tries to open an audio / video file.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

from ..errors import NotImplementedReaderError

if TYPE_CHECKING:
    from faster_whisper import WhisperModel


_DEFAULT_MODEL = "base"
_ENV_MODEL = "FYLE_WHISPER_MODEL"


def _require_faster_whisper():
    """Lazy-import faster_whisper, raising a helpful error if absent."""
    try:
        import faster_whisper  # noqa: F401 — imported for side-effect availability
    except ImportError as e:
        raise NotImplementedReaderError(
            "Transcription requires the 'faster-whisper' package. "
            "Install the optional extra: pip install 'fyle[audio]' "
            "(or 'fyle[video]' for video support)."
        ) from e
    return faster_whisper


@lru_cache(maxsize=1)
def _get_model(size: str) -> "WhisperModel":
    """Load (and memoise) the Whisper model.

    Cached per-size for the life of the process — transcribing ten files
    in a loop should not reload the 140 MB model ten times.
    """
    fw = _require_faster_whisper()
    return fw.WhisperModel(size, device="cpu", compute_type="int8")


def load_model(size: Optional[str] = None) -> "WhisperModel":
    """Return the Whisper model, honouring ``FYLE_WHISPER_MODEL`` override."""
    chosen = size or os.environ.get(_ENV_MODEL) or _DEFAULT_MODEL
    return _get_model(chosen)


def model_size() -> str:
    """Return the active model-size string (for ``meta.warnings`` reporting)."""
    return os.environ.get(_ENV_MODEL) or _DEFAULT_MODEL


def transcribe(path: str) -> tuple[list[dict], dict]:
    """Transcribe ``path`` and return ``(segments, info)``.

    ``segments`` is a list of ``{"start", "end", "text"}`` dicts (floats
    for timestamps, seconds). ``info`` is a dict with ``language``,
    ``language_probability`` and ``duration``.

    Exhausts the faster-whisper generator eagerly so callers can reason
    about the result as plain data.
    """
    model = load_model()
    # ``beam_size=1`` keeps it fast (greedy). Agents don't need the small
    # WER boost from beam_size=5 given the quality/speed trade-off.
    seg_iter, info = model.transcribe(path, beam_size=1, vad_filter=False)
    segments = [
        {"start": float(s.start), "end": float(s.end), "text": s.text.strip()}
        for s in seg_iter
    ]
    info_dict = {
        "language": getattr(info, "language", None),
        "language_probability": float(getattr(info, "language_probability", 0.0)),
        "duration": float(getattr(info, "duration", 0.0)),
    }
    return segments, info_dict


def format_timestamp(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS`` (dropping the hour if under an hour)."""
    if seconds < 0 or seconds != seconds:  # handles NaN too
        seconds = 0.0
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_transcript(segments: list[dict]) -> str:
    """Render segments as ``[MM:SS] text`` lines separated by blank lines.

    Blank lines between segments keep the transcript readable and give
    LLM chunkers a natural split point when segmentation matters.
    """
    if not segments:
        return "_(no speech detected)_"
    return "\n\n".join(
        f"[{format_timestamp(s['start'])}] {s['text']}" for s in segments if s["text"]
    ) or "_(no speech detected)_"
