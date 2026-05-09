"""Video reader.

File naming rule: ``scenedetect.py`` — the core driver that picks
keyframes. The reader also invokes ``faster_whisper`` for the audio
track. Heavy deps (PyAV, scenedetect, CTranslate2) are optional; see
``pyproject.toml`` ``[project.optional-dependencies].video``.
"""
from __future__ import annotations

from . import scenedetect  # noqa: F401
