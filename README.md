# Archive Workbench

Archive Workbench is a tool for reading scanned historical documents. You upload a page or PDF, get a transcription, optionally a translation, and can export the text. I built it for my own research on Kittur fort, where the sources are in English, Portuguese, Kannada and related scripts.

## Status

This repository is a working prototype. The version on `main` uses a commercial vision language model (Anthropic Claude) for OCR and research. That is fine for personal use with your own API key, but it is not open enough for shared research infrastructure. The plan is to move the default path to free, local engines (Tesseract and PP-OCR) and keep commercial models as an optional choice when you supply your own key. A fuller local-first design lives on the `cursor/archive-workbench-v1-9d5b` branch.

## What it does

- Upload scans or PDFs and pick pages
- Transcribe with a vision model (or mock mode with no key)
- Export to searchable PDF, Word, Markdown, plain text and JSON
- Optional cited web research against the transcription
- Spec for the longer-term workbench design: `spec.md`

## Run locally

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # set ANTHROPIC_API_KEY, or leave empty for mock mode
.venv/bin/uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000

## Configuration

Copy `.env.example` to `.env`. Never commit `.env`. Useful variables:

- `ANTHROPIC_API_KEY` — required for real OCR; without it the app runs in mock mode
- Optional model overrides: `MODEL_TIER1`, `MODEL_TIER2`, `MODEL_TIER3`, `MODEL_RESEARCH`

## Licence

Apache License 2.0. See `LICENSE`.

## Author

Praveen D Chougale
