# Archive Workbench

Archive Workbench is a tool for reading scanned historical documents. You upload a page or PDF, get a transcription, optionally a translation, and can export the text. I built it for my own research on Kittur fort, where the sources are in English, Portuguese, Kannada and related scripts.

## Status

The personal server on `main` can use Anthropic Claude for OCR and research when you set your own API key. That key is for your own machine. The public edition does not use it.

## Public edition

Anyone can open the public edition without an account. Transcription runs in the visitor's browser with Tesseract (English, Portuguese, or Kannada). A born-digital PDF keeps its text layer. The visitor can correct the text and download TXT, Markdown, JSON, or DOCX.

Documents are not uploaded and are not stored on the server. There is no shared history, no admin view, and no web research, because research would send text to a paid API. Refreshing the tab clears the session. Limits are 3 files, 8 MB each, and 5 pages each. TIFF is not decoded in the browser; use PDF, PNG, JPEG, or WebP.

The site is the `docs/` directory. GitHub Pages serves it at https://praveenmaths89.github.io/archive-workbench/ when Pages is enabled for this repository. `.github/workflows/pages.yml` publishes `docs/` on each push to `main`.

## Personal server

Leave `PUBLIC_MODE` unset. With `ANTHROPIC_API_KEY` set, OCR and web research use your key. Without a key, the server stays in mock mode. Do not put that key on a server that strangers can reach.

`PUBLIC_MODE=1` is the locked-down server mode: local Tesseract only, the configured API key is ignored, web research is off, and each browser can open only its own uploads. Those uploads expire after 24 hours. Jobs created without a visitor session, including an existing personal archive, are not listed and are not deleted. If a host sets `PORT` and neither `PUBLIC_MODE=1` nor `APP_PASSWORD`, the process refuses to start.

The `Dockerfile` builds that public server mode. It is not deployed from here. Hugging Face Docker Spaces on the free CPU tier now require a paid PRO subscription, and this change does not buy one or attach a GPU. Vercel and Firebase were not connected, and they are a poor fit for this long-running OCR process without a billed backend.

## What it does

- Upload scans or PDFs and pick pages
- Transcribe in the browser, or with Claude on your own server
- Export to Word, Markdown, plain text and JSON. The personal server also writes a searchable PDF
- Cited web research stays on the personal server, where you supply the key
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

- `ANTHROPIC_API_KEY` — personal OCR and research only. Ignored when `PUBLIC_MODE=1`
- `PUBLIC_MODE` — set to `1` on any shared server
- Optional model overrides: `MODEL_TIER1`, `MODEL_TIER2`, `MODEL_TIER3`, `MODEL_RESEARCH`

## Licence

Apache License 2.0. See `LICENSE`.

## Author

Praveen D Chougale
