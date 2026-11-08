# Archive Workbench

Archive Workbench is a tool for reading scanned historical documents. You upload a page or PDF, get a transcription, optionally a translation, and can export the text. I built it for my own research on Kittur fort, where the sources are in English, Portuguese, Kannada and related scripts.

## Status

The personal server on `main` can use Anthropic Claude for OCR and research when you set your own API key. That key is for your own machine. The public edition does not use it.

## Public edition

Anyone can open the public edition without an account. Transcription runs in the visitor's browser with Tesseract (English, Portuguese, or Kannada). A born-digital PDF keeps its text layer. The visitor can correct the text and download TXT, Markdown, JSON, or DOCX.

Documents are not uploaded and are not stored on the server. There is no shared history, no admin view, and no web research, because research would send text to a paid API. Refreshing the tab clears the session. Limits are 3 files, 8 MB each, and 5 pages each. TIFF is not decoded in the browser; use PDF, PNG, JPEG, or WebP.

The site is the `docs/` directory, published by `.github/workflows/pages.yml` to https://praveenmaths89.github.io/archive-workbench/. That site does not run the Python server.

## Personal server

Leave `PUBLIC_MODE` and `HOSTED_MODE` unset. With `ANTHROPIC_API_KEY` set, OCR and web research use your key. Without a key, the personal server stays in mock mode.

`PUBLIC_MODE=1` is a separate local-OCR mode: Tesseract only, the API key is ignored, and web research is off. It is not the Render service.

`HOSTED_MODE=1` is the shared full server. Claude OCR and web search stay on, and both use the single server `ANTHROPIC_API_KEY`. Visitors do not bring a key. Each browser can open only its own uploads, research, and exports. Those visitor uploads expire after 24 hours. Jobs with no visitor id, including a personal archive, are not listed and are not deleted. Calls are billed to the Anthropic account that owns the server key. The quotas below are technical limits on a small free instance. They are not a spending cap.

If a host sets `PORT` and neither `HOSTED_MODE` nor `PUBLIC_MODE` is on and `APP_PASSWORD` is empty, the process refuses to start.

## Render free service

`render.yaml` and the `Dockerfile` target Render's free web service (0.1 CPU, 512 MB, 750 hours a month). The free instance sleeps after 15 minutes without a request and keeps no disk across sleep or redeploy, so uploads and the in-memory session secret are lost then. The image listens on `$PORT` and serves `/healthz`. It does not contain an API key.

Set `ANTHROPIC_API_KEY` in the Render dashboard as a secret. Do not commit it. Without that secret the service still boots, and scan OCR and web search respond that the key is not configured instead of returning placeholder text. Born-digital PDFs still use their text layer.

```bash
# personal
uvicorn app.main:app --port 8000

# hosted mode, key from the environment, not from the visitor
HOSTED_MODE=1 ANTHROPIC_API_KEY=... uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
```

Technical limits in hosted mode: 3 files per job, 50 MB each, at most 5 pages read at a time, 6 jobs an hour, 20 pages a day, 8 stored jobs, one in-flight job per session, one worker in the Render image. A longer PDF is stored with its page count and is not sent to the model until you choose a range such as `1-5`. GitHub Pages at https://praveenmaths89.github.io/archive-workbench/ is unchanged and is not this server.

## What it does

- Upload scans or PDFs and pick pages
- Transcribe in the browser, or with Claude on your own server
- Export to Word, Markdown, plain text and JSON. The personal server also writes a searchable PDF
- Cited web research on the personal server and on the hosted server, both using the server key
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

- `ANTHROPIC_API_KEY` — server key for Claude OCR and web search. Ignored when `PUBLIC_MODE=1`. Required for real OCR and search when `HOSTED_MODE=1`. Set it only in the environment or the host secret store.
- `HOSTED_MODE` — set to `1` for the shared full server (Render)
- `PUBLIC_MODE` — set to `1` for local Tesseract only, with web search off
- Optional model overrides: `MODEL_TIER1`, `MODEL_TIER2`, `MODEL_TIER3`, `MODEL_RESEARCH`

## Licence

Apache License 2.0. See `LICENSE`.

## Author

Praveen D Chougale
