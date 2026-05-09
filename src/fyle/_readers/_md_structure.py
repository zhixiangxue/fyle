"""Markdown structural extraction shared by every reader whose ``Page.text``
is Markdown (currently: ``markdown``, ``docx``, ``html``).

The contract is deliberately narrow: given a Markdown string, return the
``Table`` and ``Image`` objects that appear in it. Page text itself is not
modified — this is *extraction only*, so the caller's passthrough / rendering
decisions remain untouched.

Design notes:
- Parsing is delegated to ``markdown-it-py`` (GFM-like, with the table
  plugin enabled). We never regex-parse Markdown structure ourselves
  (see design doc §12.0).
- HTML ``<img>`` tags embedded in the Markdown are picked up via
  BeautifulSoup when ``include_html_img=True``. This matters in practice
  because:
    - README / docs frequently write logos and badges as ``<img>`` for
      width / alignment control;
    - ``markdownify`` (used by docx & html readers) preserves HTML fragments
      it can't map to Markdown.
- Image ``data_url`` may be a ``data:image/...;base64,...`` URL (DOCX /
  PDF / HTML inline images) or a plain ``http(s)://`` URL (Markdown
  references). Both are valid per the ``Image`` contract.
- Every failure path is non-fatal: if markdown-it-py or bs4 fail we append
  a warning and return whatever we managed to collect. The reader's main
  job (producing ``Page.text``) should never be blocked by optional
  structural extraction.
"""
from __future__ import annotations

from typing import Optional

from .._core.document import Image, Table


def extract_tables(
    md_text: str,
    *,
    page: int = 1,
    warnings: Optional[list[str]] = None,
) -> list[Table]:
    """Extract GFM pipe tables from Markdown.

    ``table.text`` is a verbatim slice of the source (using ``token.map``),
    not a re-render. ``table.rows`` contains string cells.
    """
    warnings = warnings if warnings is not None else []
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        warnings.append("markdown-it-py not installed; skipping table extraction")
        return []
    try:
        md_parser = MarkdownIt().enable("table")
        tokens = md_parser.parse(md_text)
    except Exception as e:
        warnings.append(f"markdown parse failed; tables not extracted: {e}")
        return []

    lines = md_text.splitlines(keepends=True)
    tables: list[Table] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "table_open":
            headers, rows, advance = _walk_table(tokens, i)
            table_md = ""
            if tok.map:
                start, end = tok.map  # half-open
                table_md = "".join(lines[start:end]).rstrip("\n")
            tables.append(
                Table(
                    text=table_md,
                    rows=rows,
                    headers=headers,
                    page=page,
                )
            )
            i = advance
        else:
            i += 1
    return tables


def _walk_table(tokens, start_idx: int) -> tuple[list[str], list[list[str]], int]:
    """Collect ``(headers, body_rows, index_after_table_close)`` from tokens.

    markdown-it-py table token shape::

        table_open
          thead_open
            tr_open
              th_open, inline (cell), th_close  ...
            tr_close
          thead_close
          tbody_open
            tr_open
              td_open, inline (cell), td_close  ...
            tr_close
            ...
          tbody_close
        table_close
    """
    headers: list[str] = []
    rows: list[list[str]] = []
    current_row: list[str] = []
    in_thead = False

    i = start_idx + 1
    while i < len(tokens):
        tok = tokens[i]
        t = tok.type
        if t == "table_close":
            return headers, rows, i + 1
        if t == "thead_open":
            in_thead = True
        elif t == "thead_close":
            in_thead = False
        elif t == "tr_open":
            current_row = []
        elif t == "tr_close":
            if in_thead:
                headers = current_row
            else:
                rows.append(current_row)
        elif t == "inline":
            current_row.append(tok.content)
        i += 1
    return headers, rows, i


def extract_images(
    md_text: str,
    *,
    page: int = 1,
    warnings: Optional[list[str]] = None,
    include_html_img: bool = True,
) -> list[Image]:
    """Extract image references from Markdown.

    Two sources are consulted and the results are concatenated:

    1. Native Markdown ``![alt](url)`` tokens via markdown-it-py.
    2. HTML ``<img src="..." alt="...">`` tags via BeautifulSoup
       (only when ``include_html_img=True``).

    ``data_url`` carries whatever URL appeared in the source: a ``data:``
    URL for inline base64 images (DOCX, PDF, HTML inline), or a plain
    ``http(s)://`` URL for referenced images. The reader does not fetch
    remote URLs — that is an application concern.
    """
    warnings = warnings if warnings is not None else []
    images: list[Image] = []

    # 1. Markdown native images.
    try:
        from markdown_it import MarkdownIt
        md_parser = MarkdownIt().enable("table")
        tokens = md_parser.parse(md_text)
        for tok in tokens:
            children = getattr(tok, "children", None) or []
            for child in children:
                if child.type == "image":
                    src = ""
                    if getattr(child, "attrs", None):
                        src = child.attrs.get("src") or ""
                    alt = (child.content or "").strip()
                    if src:
                        images.append(
                            Image(
                                data_url=src,
                                data=b"",
                                caption=alt or None,
                                page=page,
                            )
                        )
    except ImportError:
        warnings.append(
            "markdown-it-py not installed; skipping Markdown image extraction"
        )
    except Exception as e:
        warnings.append(f"Markdown image extraction failed: {e}")

    # 2. HTML <img> tags mixed into the Markdown (common for badges / logos).
    if include_html_img:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(md_text, "html.parser")
            for tag in soup.find_all("img"):
                src = (tag.get("src") or "").strip()
                if not src:
                    continue
                alt = (tag.get("alt") or "").strip()
                images.append(
                    Image(
                        data_url=src,
                        data=b"",
                        caption=alt or None,
                        page=page,
                    )
                )
        except ImportError:
            warnings.append(
                "beautifulsoup4 not installed; skipping HTML <img> extraction"
            )
        except Exception as e:
            warnings.append(f"HTML <img> extraction failed: {e}")

    return images
