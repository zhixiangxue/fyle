"""DOCX reader — uses ``mammoth`` for Word → HTML → Markdown conversion.

File name inside the subpackage is the *core driver library* (``mammoth``);
``markdownify`` is a post-processor in the DOCX → HTML → Markdown chain.
"""
from . import mammoth  # noqa: F401
