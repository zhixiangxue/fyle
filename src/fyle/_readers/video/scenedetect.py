"""Video reader — scene-change keyframes + Whisper transcription.

What ``doc.text`` looks like
----------------------------
A single Markdown page with three sections:

1. **Header** — source name, duration, keyframe count, detected language.
2. **Keyframes list** — timestamps of every extracted frame so the LLM
   can cross-reference by time without decoding the image bytes.
3. **Transcript** — ``[MM:SS] text`` lines produced by faster-whisper.

``doc.images`` carries the actual frames as ``data:image/jpeg;base64,...``
URLs. Each image's ``caption`` is the ``MM:SS`` timestamp so the LLM can
join the visual and the transcript by time.

Why this design
---------------
Video is just *audio track + sequence of images* to an LLM. Rather than
invent a multimodal format, we emit the same text shape as the audio
reader (timestamped transcript) plus a normal ``doc.images`` list that
any downstream multimodal prompt already knows how to splice in.

Scene detection: ``scenedetect.ContentDetector``. Content-aware delta on
HSV histograms catches slide changes / cut edits / camera moves —
exactly what makes a new frame informative. The frame picked per scene
is the scene's temporal midpoint, which is typically the most stable
(post-transition, pre-next-transition) sample.

No hidden caps
--------------
We emit one keyframe per detected scene. Long / busy videos can
produce hundreds of frames, but silently truncating would hide data
from the caller — callers who need a cap can slice ``doc.images``
themselves. The only warning-level observation we log is the final
count so the caller sees it at a glance.

File naming rule: ``scenedetect.py`` — the characteristic driver that
distinguishes this from a hypothetical alternative video reader (e.g.
one using a vision-language model for shot boundaries).
"""
from __future__ import annotations

import base64
import io
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .. import _whisper
from ..base import Reader
from ..._core.document import Document, Image, Meta, Page
from ...errors import NotImplementedReaderError, ParseError


_KNOWN_VIDEO_SUFFIXES = {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm"}


class SceneDetectVideoReader(Reader):
    name = "video-scenedetect"
    formats = ("video",)
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
            raise ParseError("video-scenedetect reader: input is empty")

        # Lazy-import both heavy deps so ``import fyle`` stays cheap when
        # the user never opens a video file.
        av = _require_av()
        detect, ContentDetector = _require_scenedetect()

        warnings: list[str] = []
        suffix = _pick_suffix(source_name)

        tmp = tempfile.NamedTemporaryFile(
            prefix="fyle-video-",
            suffix=suffix,
            delete=False,
        )
        try:
            tmp.write(data)
            tmp.close()

            # 1. Scene boundaries. On failure we still try keyframe+ASR so
            #    the caller gets a partial Document rather than a crash.
            try:
                scenes = detect(tmp.name, ContentDetector())
            except Exception as e:
                warnings.append(f"scene detection failed: {e}")
                scenes = []

            midpoints = [
                (s.get_seconds() + e.get_seconds()) / 2 for s, e in scenes
            ]
            # Fall back to a single opening frame if scenedetect returned
            # nothing (e.g. ultra-short clips or a single static scene).
            if not midpoints:
                midpoints = [0.0]
                warnings.append(
                    "no scene boundaries detected; falling back to one opening frame"
                )

            # 2. Keyframes.
            frames = _extract_keyframes(av, tmp.name, midpoints, warnings)

            # 3. Transcription (same file — faster-whisper / PyAV pick
            #    the audio track automatically).
            try:
                segments, info = _whisper.transcribe(tmp.name)
            except Exception as e:
                warnings.append(f"audio transcription failed: {e}")
                segments = []
                info = {}
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        # 4. Document assembly.
        images = _build_images(frames)
        page_text = _render_page_text(
            source_name=source_name,
            duration_sec=float(info.get("duration", 0.0) or 0.0),
            language=info.get("language"),
            keyframe_ts=[ts for ts, _ in frames],
            segments=segments,
        )

        if info.get("language"):
            warnings.append(
                f"detected language: {info['language']} "
                f"(p={info.get('language_probability', 0):.2f})"
            )
        if info.get("duration"):
            warnings.append(
                f"video duration: {_whisper.format_timestamp(info['duration'])}"
            )
        warnings.append(f"whisper model: {_whisper.model_size()}")
        warnings.append(f"keyframes: {len(frames)}")

        title = Path(source_name).stem if source_name else None
        page = Page(text=page_text, number=1, images=images)
        meta = Meta(
            format="video",
            pages=1,
            size=len(data),
            title=title,
            reader=self.name,
            created_at=datetime.now(timezone.utc),
            warnings=warnings,
        )
        return Document(pages=[page], meta=meta)


# ----------------------------------------------------------------------
# Lazy-import guards (separate so each has its own error message)
# ----------------------------------------------------------------------

def _require_av():
    try:
        import av  # noqa: F401
    except ImportError as e:
        raise NotImplementedReaderError(
            "Video reading requires the 'av' (PyAV) package. "
            "Install the optional extra: pip install 'fyle[video]'."
        ) from e
    return av


def _require_scenedetect():
    try:
        from scenedetect import detect, ContentDetector
    except ImportError as e:
        raise NotImplementedReaderError(
            "Video reading requires the 'scenedetect' package. "
            "Install the optional extra: pip install 'fyle[video]'."
        ) from e
    return detect, ContentDetector


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _pick_suffix(source_name: Optional[str]) -> str:
    """Return a video suffix PyAV will recognise. Fallback to ``.mp4``."""
    if source_name:
        ext = Path(source_name).suffix.lower()
        if ext in _KNOWN_VIDEO_SUFFIXES:
            return ext
    return ".mp4"


def _extract_keyframes(
    av_module,
    path: str,
    timestamps_sec: list[float],
    warnings: list[str],
) -> list[tuple[float, bytes]]:
    """For each target timestamp (seconds), return the nearest decoded frame.

    Output is a list of ``(timestamp_sec, jpeg_bytes)`` tuples in the
    same order as ``timestamps_sec``. Failures for individual timestamps
    are recorded in ``warnings`` and the timestamp is skipped rather
    than raising — we prefer a partial video over none.
    """
    results: list[tuple[float, bytes]] = []

    try:
        container = av_module.open(path)
    except Exception as e:
        warnings.append(f"failed to open video for keyframe extraction: {e}")
        return results

    try:
        try:
            stream = container.streams.video[0]
        except (IndexError, AttributeError):
            warnings.append("no video stream found for keyframe extraction")
            return results

        time_base = float(stream.time_base) if stream.time_base else 0.0
        if time_base <= 0:
            warnings.append("video stream reports an invalid time_base; skipping keyframes")
            return results

        for ts_sec in timestamps_sec:
            try:
                frame = _grab_frame_at(container, stream, ts_sec, time_base)
            except Exception as e:
                warnings.append(f"keyframe extraction at {ts_sec:.2f}s failed: {e}")
                continue
            if frame is None:
                continue
            try:
                img = frame.to_image()  # PIL Image
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                results.append((ts_sec, buf.getvalue()))
            except Exception as e:
                warnings.append(f"JPEG encode at {ts_sec:.2f}s failed: {e}")
    finally:
        try:
            container.close()
        except Exception:
            pass

    return results


def _grab_frame_at(container, stream, ts_sec: float, time_base: float):
    """Seek to the nearest keyframe before ``ts_sec`` and decode forward."""
    ts_units = int(ts_sec / time_base)
    container.seek(ts_units, stream=stream, backward=True)
    best = None
    for frame in container.decode(stream):
        if frame.pts is None:
            continue
        frame_sec = float(frame.pts * stream.time_base)
        if frame_sec >= ts_sec:
            return frame
        best = frame
    return best


def _build_images(frames: list[tuple[float, bytes]]) -> list[Image]:
    images: list[Image] = []
    for ts, jpeg_bytes in frames:
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        data_url = f"data:image/jpeg;base64,{b64}"
        images.append(
            Image(
                data_url=data_url,
                data=jpeg_bytes,
                caption=_whisper.format_timestamp(ts),
                page=1,
            )
        )
    return images


def _render_page_text(
    *,
    source_name: Optional[str],
    duration_sec: float,
    language: Optional[str],
    keyframe_ts: list[float],
    segments: list[dict],
) -> str:
    title = source_name or "(unnamed video)"
    dur = _whisper.format_timestamp(duration_sec) if duration_sec else "-"
    lang = language or "-"

    if keyframe_ts:
        kf_lines = "\n".join(
            f"- `{_whisper.format_timestamp(ts)}` — keyframe {i + 1}"
            for i, ts in enumerate(keyframe_ts)
        )
    else:
        kf_lines = "_(no keyframes extracted)_"

    transcript = _whisper.format_transcript(segments)

    return (
        f"# Video: {title}\n"
        "\n"
        f"- Duration: `{dur}`\n"
        f"- Keyframes: {len(keyframe_ts)}\n"
        f"- Language: `{lang}`\n"
        "\n"
        "## Keyframes\n"
        "\n"
        f"{kf_lines}\n"
        "\n"
        "(full frame bytes are in `doc.images`, each caption is its timestamp)\n"
        "\n"
        "## Transcript\n"
        "\n"
        f"{transcript}"
    )
