"""Audio reader.

File naming rule: ``faster_whisper.py`` — the core driver library.
The heavy deps (CTranslate2, PyAV, onnxruntime) are optional and only
required at read-time; see ``pyproject.toml`` ``[project.optional-dependencies].audio``.
"""
from __future__ import annotations

from . import faster_whisper  # noqa: F401
