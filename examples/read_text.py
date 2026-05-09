"""Interactive plain-text reader example.

Usage:
    python examples/read_text.py

Accepts any plain-text file — source code, configs, logs, structured
data, lightweight markup, and more. A non-exhaustive list:

    .py .pyi .js .ts .jsx .tsx .vue .svelte
    .java .kt .scala .go .rs .swift .c .h .cpp .cs
    .rb .php .lua .dart .r .jl .hs .ex .erl
    .sh .bash .zsh .ps1 .bat
    .json .jsonl .yaml .toml .xml .svg .tsv
    .ini .cfg .conf .env .properties
    .sql .graphql .proto
    .rst .adoc .tex .org
    .log .diff .patch
    .txt .text .readme

The content lands in ``doc.text`` unchanged — no Markdown escaping —
so whatever the author typed is what you see. Binary / structured
formats (``.pdf`` / ``.docx`` / ``.xlsx`` / images / audio / video)
have dedicated readers and are routed automatically by ``fyle.open``.
"""
from _common import run


PROMPT = (
    "Enter a plain-text source "
    "(code / config / log / JSON / YAML / SQL / ... — "
    "local path or http(s):// URL), or blank to quit."
)


if __name__ == "__main__":
    raise SystemExit(run(PROMPT))
