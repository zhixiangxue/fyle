"""Interactive video reader example.

Usage:
    python examples/read_video.py

Accepts ``.mp4`` / ``.m4v`` / ``.mov`` / ``.avi`` / ``.mkv`` / ``.webm``
files, local path or ``http(s)://`` URL.

What the video reader does
--------------------------
Turns a video into what an LLM can actually see: a time-stamped
transcript **plus** a sequence of keyframes, both anchored to the same
``MM:SS`` timeline so the model can join audio and vision.

1. **Scene detection** (``scenedetect.ContentDetector``) finds every
   meaningful scene change (slide change, cut, camera move).
2. **Keyframe extraction** (PyAV) grabs the middle frame of each scene
   and attaches it to ``doc.images`` with the timestamp as caption.
3. **Audio transcription** (``faster-whisper`` ``base`` model, CPU /
   int8) renders the audio track as ``[MM:SS] text`` segments in
   ``doc.text``.

No hidden caps: we emit one keyframe per detected scene. A 2-hour
tutorial with 40 slide changes yields 40 images; you decide whether to
slice. ``meta.warnings`` reports the final keyframe count.

First-run model download
------------------------
The Whisper model downloads on first use (~140 MB). Offline afterwards.

Requires the optional extra:
    pip install 'fyle[video]'
"""
from _common import run


PROMPT = (
    "Enter a video source "
    "(.mp4 / .m4v / .mov / .avi / .mkv / .webm — local path or http(s):// URL), "
    "or blank to quit."
)


if __name__ == "__main__":
    raise SystemExit(run(PROMPT))
