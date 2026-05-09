"""Import every reader subpackage to trigger auto-registration.

Reader subclasses register themselves via ``__init_subclass__`` in
``base.py``, which only fires once the defining module is imported. This
file is therefore the single place that decides which readers are available
at runtime — add one ``from . import <subpkg>`` line per new reader subpackage.

File-name convention inside each subpackage: every reader implementation
file is named after its *core driver library* (for example ``mammoth.py``,
``markdownify.py``, ``openpyxl.py``, ``pymupdf4llm.py``, ``stdlib.py``).
Post-processors (e.g. ``tabulate``, ``beautifulsoup4``) do not determine
the file name. This keeps the door open for same-format alternative
implementations to co-exist under their own library names.
"""
# Batch 1 (v0.2): text family — text / markdown / csv.
# Batch 2 (v0.3): structured documents — docx / html / xlsx.
# Batch 3 (v0.4): pptx / image.
# Batch 4 (placeholder): audio / video — reserve the format slots; readers
# raise ``NotImplementedReaderError`` until concrete backends land.
from . import pdf  # noqa: F401
from . import text  # noqa: F401
from . import markdown  # noqa: F401
from . import csv  # noqa: F401
from . import docx  # noqa: F401
from . import html  # noqa: F401
from . import xlsx  # noqa: F401
from . import pptx  # noqa: F401
from . import image  # noqa: F401
from . import sqlite  # noqa: F401
from . import archive  # noqa: F401
from . import audio  # noqa: F401
from . import video  # noqa: F401
