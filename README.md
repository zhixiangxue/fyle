<div align="center">

<img src="https://raw.githubusercontent.com/zhixiangxue/fyle/main/docs/assets/logo.png" alt="fyle" width="120">

[![PyPI](https://img.shields.io/pypi/v/fyle.svg)](https://pypi.org/project/fyle/)
[![Python](https://img.shields.io/pypi/pyversions/fyle.svg)](https://pypi.org/project/fyle/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Downloads](https://img.shields.io/pypi/dm/fyle.svg)](https://pypi.org/project/fyle/)

**Any file in. Clean Markdown out. LLM ready.**

A lightweight library that turns PDF, DOCX, XLSX, audio, video, and ~100 more formats into the Markdown your LLM already understands.

</div>

---

## What is this?

A lightweight library for reading files. What makes it different: the output is **LLM-ready** — clean Markdown you can feed straight into any model, no post-processing, no cleanup.

**One line. Every common file. LLM-ready Markdown.** Point fyle at a path, URL, or raw bytes — what comes back is already something a model can read natively. No OCR plumbing, no format-specific parser glue, no prompt engineering to "please strip the headers and footers".

```python
import fyle

text = fyle.read("report.pdf")   # or .docx / .xlsx / .mp3 / .mp4 / an http(s) URL / raw bytes
llm.complete(text)               # that's it.
```

Works out of the box on:

- **PDF / DOCX / XLSX / PPTX / HTML / Markdown / CSV** — parsed into Markdown
- **Images** — base64 `data:image/...` URLs ready for multimodal models
- **Audio / video** — local ASR transcripts with `[MM:SS]` timestamps (+ keyframes for video)
- **SQLite** — schema preview + fluent `doc.table(t).query(sql)` API
- **Archive** — safe extraction + Markdown manifest, agent decides what to open next
- **~100 source / config / log formats** — passthrough as plain text

> 100% local. No cloud APIs. No telemetry. No API keys.
> Just `fyle.open(...)` and the file becomes something an LLM can see.

---

## Install

```bash
pip install fyle
```

Audio / video transcription are opt-in extras (native wheels + a ~140 MB model on first run):

```bash
pip install 'fyle[audio]'   # faster-whisper
pip install 'fyle[video]'   # faster-whisper + PySceneDetect + PyAV
```

---

## Quick start

```python
import fyle

doc = fyle.open("report.pdf")
# or: fyle.open("https://example.com/report.pdf")
# or: fyle.open(raw_bytes)   # format auto-detected from magic bytes

# Three views of the same document:
print(doc.text)            # pure content — whatever the reader produced
print(str(doc))            # LLM-ready: filename + format + size header, then content
print(repr(doc))           # short debug line for logs

# Typical usage — hand the whole thing to your model in one line:
llm.complete(str(doc))     # filename carries real signal the model can use

print(doc.meta.format)     # "pdf"
print(doc.meta.ext)        # "pdf"
print(doc.pages[0].text)   # just page 1

# One-shot convenience: str in, LLM-ready string out (same as str(fyle.open(...)))
text = fyle.read("report.pdf")

# Check which readers are available in your install
fyle.readers()
# {"pdf": ["pymupdf4llm*"], "audio": ["faster-whisper*"], ...}
```

---

## Supported formats

| Family | Extensions | Reader |
|---|---|---|
| PDF | `.pdf` | [pymupdf4llm](https://pypi.org/project/pymupdf4llm/) |
| Word | `.docx` | mammoth |
| Excel | `.xlsx` | openpyxl + tabulate |
| PowerPoint | `.pptx` | python-pptx |
| Web | `.html` `.htm` | markdownify |
| Markdown | `.md` `.markdown` | markdown-it-py |
| CSV | `.csv` | stdlib + tabulate |
| Image | `.png` `.jpg` `.jpeg` `.webp` | Pillow → base64 data URL |
| Audio | `.mp3` `.m4a` `.wav` `.flac` `.ogg` | faster-whisper (CPU, int8) |
| Video | `.mp4` `.m4v` `.mov` `.avi` `.mkv` `.webm` | PySceneDetect + Whisper |
| Database | `.db` `.sqlite` `.sqlite3` | stdlib + fluent SQL API |
| Archive | `.zip` `.tar` `.gz` `.bz2` `.xz` ... | stdlib — extract to disk + manifest |
| Text | `.py` `.js` `.go` `.rs` `.java` `.json` `.yaml` `.toml` `.sql` `.log` ... (~100) | passthrough |

---

## Audio & video

```python
doc = fyle.open("meeting.mp4")

print(doc.text)
# # Video: meeting.mp4
#
# - Duration: `12:34`
# - Keyframes: 8
# - Language: `en`
#
# ## Transcript
#
# [00:00] Welcome everyone to the quarterly review...

for img in doc.images:
    print(img.caption, img.src[:32])
    # "02:17"  "data:image/jpeg;base64,/9j/4AA..."
```

First call downloads the Whisper `base` model (~140 MB). CPU only — no GPU needed.
Override with `FYLE_WHISPER_MODEL=small` (or `medium` / `large-v3`) for higher quality.

---

## SQLite

```python
doc = fyle.open("chinook.db")

for page in doc.pages:
    print(page.name)          # table or view name
    print(page.text)          # schema + sample rows

rows = doc.table("Customer").query(
    "SELECT Country, COUNT(*) AS n FROM Customer GROUP BY Country ORDER BY n DESC"
)
```

---

## Archive

```python
doc = fyle.open("~/Downloads/invoices.zip")

print(doc.text)                # Markdown listing of extracted files
print(doc.meta.warnings)       # ["extracted to: /.../invoices/"]

# Agent's next step: fyle.open(one of the extracted files)
```

Refuses `..` path traversal and symlink escapes; extracts to the archive's sibling directory.

---

## Chunking for RAG

```python
for chunk in doc.chunks(max_tokens=4000, overlap=200):
    embed(chunk.text)
    # chunk.tokens / chunk.page_range also available
```

---

## Notes

1. **Offline only.** Every reader runs locally. The audio/video reader downloads the Whisper model from Hugging Face on first run; after that, no network.
2. **Archive reader is list-only.** It extracts files to disk and returns a manifest — it does not recursively parse contents. The agent decides what to open next.
3. **Alpha.** Core is stable, but APIs may move between `0.x` releases.

---

## Feedback

Issues, PRs, and stars are welcome.

---

## License

MIT © 2026 zhixiangxue

---

<div align="right"><img src="https://raw.githubusercontent.com/zhixiangxue/fyle/main/docs/assets/logo.png" alt="fyle" width="120"></div>
