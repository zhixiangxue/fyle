"""HTML reader — uses ``markdownify`` for HTML → Markdown conversion.

File name inside the subpackage is the *core driver library* (``markdownify``);
``beautifulsoup4`` is a pre-processor (strip ``<head>``, read ``<title>``).
"""
from . import markdownify  # noqa: F401
