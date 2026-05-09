"""CSV reader — renders a CSV as a single Markdown table via ``tabulate``.

File name inside the subpackage is the *core driver library* (the Python
standard library's ``csv`` module); ``tabulate`` is a post-processor.
"""
from . import stdlib  # noqa: F401
