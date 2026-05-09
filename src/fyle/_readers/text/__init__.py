"""Plain-text reader — passthrough of ``.txt`` / ``.log`` files.

File name inside the subpackage is the *core driver library* of the
reader implementation (here: the Python standard library), so any future
alternative implementation can live alongside under its own library name.
"""
from . import stdlib  # noqa: F401
