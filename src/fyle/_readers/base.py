"""Reader abstract base class — every reader subclasses this.

Subclasses are auto-registered via ``__init_subclass__`` at definition time;
no manual registration call is needed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .._core.document import Document
from .._core.registry import _register


class Reader(ABC):
    """Abstract base class for all readers.

    Subclasses must define the following class attributes:
      name: str                   — globally unique reader name (e.g. ``"pymupdf4llm"``).
      formats: tuple[str, ...]    — supported format names (e.g. ``("pdf",)``).
      is_default: bool = False    — whether this is the default reader for each
                                    format listed in ``formats``.

    Subclasses must implement ``read(self, data, *, source_name=None, source_path=None) -> Document``.
    """

    name: str = ""
    formats: tuple[str, ...] = ()
    is_default: bool = False

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        # Only auto-register concrete subclasses; skip intermediate abstract bases
        # that still carry @abstractmethod definitions.
        if getattr(cls, "__abstractmethods__", None):
            return
        if not cls.name or not cls.formats:
            # Subclasses used purely as organisational layers (no name/formats)
            # are allowed and are skipped by the registry.
            return
        _register(cls)

    @abstractmethod
    def read(
        self,
        data: bytes,
        *,
        source_name: Optional[str] = None,
        source_path: Optional[str] = None,
    ) -> Document:
        """Parse raw bytes and return a ``Document``.

        The dispatcher (``_core.api._normalize``) is responsible for unifying
        path / bytes / file-like / URL inputs into bytes before the reader
        runs; readers never handle polymorphic inputs themselves.

        Args:
            data: In-memory file contents as ``bytes``.
            source_name: Original file name (from a local path or URL path),
                used as a fallback for ``meta.title``.
            source_path: Absolute filesystem path of a local file source, or
                ``None`` for URL / bytes / file-like inputs. Most readers
                ignore this; the archive reader uses it to extract into the
                same directory as the source file.

        Returns:
            A ``Document``. Fatal failures raise ``fyle.ParseError``; partial
            failures are recorded in ``doc.meta.warnings``.
        """
        raise NotImplementedError
