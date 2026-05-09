"""Interactive audio reader example.

Usage:
    python examples/read_audio.py

Accepts ``.mp3`` / ``.m4a`` / ``.wav`` / ``.flac`` / ``.ogg`` files,
local path or ``http(s)://`` URL.

What the audio reader does
--------------------------
Transcribes the audio to Markdown using ``faster-whisper`` (CPU / int8,
``base`` model, ~140 MB). Each spoken segment becomes one
``[MM:SS] text`` line in ``doc.text`` so the LLM can cite moments.
Language is auto-detected — no prompt needed for Chinese, English,
Spanish, etc.

First-run model download
------------------------
The Whisper ``base`` model (~140 MB) downloads automatically from
Hugging Face the first time you run this. Subsequent runs are fully
offline. Cached under ``~/.cache/huggingface/hub/``.

Override the model size via env var:
    FYLE_WHISPER_MODEL=small python examples/read_audio.py

Requires the optional extra:
    pip install 'fyle[audio]'
"""
from _common import run


PROMPT = (
    "Enter an audio source "
    "(.mp3 / .m4a / .wav / .flac / .ogg — local path or http(s):// URL), "
    "or blank to quit."
)


if __name__ == "__main__":
    raise SystemExit(run(PROMPT))
