"""Reader registry — populated at build time, read-only at runtime.

Not a public extension point. ``_register`` is invoked only from
``_readers/base.py`` via ``__init_subclass__``; users must not register their own.
"""
from __future__ import annotations

from typing import Optional

from ..errors import ReaderNotFoundError

# Reader name -> Reader class.
_BY_NAME: dict[str, type] = {}
# Format name -> list of Reader classes, preserving registration order.
_BY_FORMAT: dict[str, list[type]] = {}
# Format name -> default Reader class for that format.
_DEFAULTS: dict[str, type] = {}


def _register(cls: type) -> None:
    """Invoked by the Reader base class from ``__init_subclass__``."""
    name = getattr(cls, "name", None)
    formats = getattr(cls, "formats", None)
    if not name or not formats:
        raise RuntimeError(
            f"Reader {cls.__name__} must define class attrs `name: str` and `formats: tuple[str, ...]`"
        )
    if name in _BY_NAME and _BY_NAME[name] is not cls:
        raise RuntimeError(f"Reader name conflict: {name!r}")
    _BY_NAME[name] = cls

    is_default = bool(getattr(cls, "is_default", False))
    for fmt in formats:
        bucket = _BY_FORMAT.setdefault(fmt, [])
        if cls not in bucket:
            bucket.append(cls)
        if is_default:
            existing = _DEFAULTS.get(fmt)
            if existing is not None and existing is not cls:
                raise RuntimeError(
                    f"Multiple default readers for format {fmt!r}: "
                    f"{existing.name} and {cls.name}"
                )
            _DEFAULTS[fmt] = cls


def validate() -> None:
    """Startup check: every registered format must have exactly one default reader.

    Fail fast if any format has readers but no default marked ``is_default=True``.
    """
    for fmt, readers in _BY_FORMAT.items():
        if fmt not in _DEFAULTS:
            raise RuntimeError(
                f"Format {fmt!r} has readers {[r.name for r in readers]} "
                f"but no default (is_default=True). Fix at startup."
            )


def resolve(fmt: str, name: Optional[str] = None) -> type:
    """Resolve a Reader class from a format and optional reader name.

    - ``name=None``: return the default reader for ``fmt``; if no reader is
      registered for ``fmt``, raise ``ReaderNotFoundError``.
    - ``name`` given but not registered: raise ``ReaderNotFoundError``.
    - ``name`` given but does not support ``fmt``: raise ``ReaderNotFoundError``.
    """
    if name is None:
        default_cls = _DEFAULTS.get(fmt)
        if default_cls is None:
            raise ReaderNotFoundError(
                f"No reader registered for format {fmt!r}. "
                f"Available: {sorted(_DEFAULTS)}"
            )
        return default_cls

    cls = _BY_NAME.get(name)
    if cls is None:
        raise ReaderNotFoundError(
            f"Reader {name!r} not found. Available: {sorted(_BY_NAME)}"
        )
    if fmt not in cls.formats:
        raise ReaderNotFoundError(
            f"Reader {name!r} does not support format {fmt!r} "
            f"(supports: {list(cls.formats)})"
        )
    return cls


def list_formats() -> list[str]:
    """Return the sorted list of formats that fyle can ingest.

    Backs the public ``fyle.accepts()`` helper. The registry is the single
    source of truth: a format appears here iff at least one Reader class
    has registered for it.
    """
    return sorted(_BY_FORMAT)


def list_all() -> dict[str, list[str]]:
    """Return ``{fmt: [name, ...]}``.

    The default reader for each format is placed first and suffixed with ``*``.
    Backs the public ``fyle.readers()`` helper.
    """
    out: dict[str, list[str]] = {}
    for fmt, readers in _BY_FORMAT.items():
        default_cls = _DEFAULTS.get(fmt)
        names: list[str] = []
        if default_cls is not None:
            names.append(f"{default_cls.name}*")
        for cls in readers:
            if cls is default_cls:
                continue
            names.append(cls.name)
        out[fmt] = names
    return out
