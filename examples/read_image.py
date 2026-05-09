"""Interactive image reader example.

Usage:
    python examples/read_image.py

Accepts ``.png`` / ``.jpg`` / ``.jpeg`` / ``.webp`` (and other common
image subtypes), local path or ``http(s)://`` URL. The reader wraps
the raw bytes as a ``data:<mime>;base64,...`` URL and places a single
Markdown image token into ``doc.text``, so the document can be fed
directly into a multimodal LLM prompt.
"""
from _common import run


PROMPT = "Enter an image source (local path or http(s):// URL), or blank to quit."


if __name__ == "__main__":
    raise SystemExit(run(PROMPT))
