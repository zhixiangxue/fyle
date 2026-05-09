"""XLSX reader — uses ``openpyxl`` + ``tabulate``; one sheet per ``Page``.

File name inside the subpackage is the *core driver library* (``openpyxl``);
``tabulate`` is a post-processor for Markdown table rendering.
"""
from . import openpyxl  # noqa: F401
