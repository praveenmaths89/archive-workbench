# Archive Workbench

Archive Workbench is a local research workbench for archaeology and history. You upload a scanned document, read it next to the page, ask questions that come back with citations, search open libraries, translate the transcription, and keep notes.

It is meant to run on your own machine. Documents stay in Postgres and a data folder on that machine. A model key can live in Settings on this computer, or in `.env` as a fallback. With no key, OCR is a free local engine and answers are quoted from the transcription instead of being written by a model.

The interface is in English, Hindi, Kannada, Marathi, Tamil, Telugu, and Bengali. The palette is parchment and seal: warm paper `#f4efe6`, ink `#1c1915`, and one seal accent `#7c2f27`, with a dark paper `#141210`. That choice is separate from the language you translate a document into.

Author: Praveen D Chougale. Licence: Apache-2.0. The design is in `spec.md`.

## Run with Docker

This is the setup to use on a Mac with Docker Desktop, including an Apple Silicon Mac. Docker Desktop includes Compose.

```bash
cp .env.example .env
docker compose up --build
```

Then open http://localhost:3000.

The first build is slow. The API image installs Tesseract (English, Kannada, Marathi, Hindi) and downloads the small multilingual embedding model. Later starts are ordinary.

Leave `LLM_API_KEY` empty in `.env` if you do not want any page or question sent to a model vendor. You can also paste a key in Settings (Anthropic, Gemini, OpenAI, or an OpenAI-compatible base URL such as Ollama). The saved key stays in Postgres on this machine. After you save, the screen shows only the last four characters. Clearing it falls back to the environment key, if there is one. You do not need to restart after saving. Only an admin can change the key once sign-in is on.

`OCR_ENGINE` is `tesseract` (the default), `ppocr`, `claude`, or `gemini`. The same choice is on the upload form and in Settings. Claude and Gemini stay disabled until a key is saved, and the worker uses Tesseract if a vision engine is requested without one. PP-OCR is the stronger free engine for printed text. The first page that uses it downloads about 40 MB of Apache-2.0 ONNX weights into the data folder (`DATA_DIR/models/ppocr`). The API image grows by the ONNX Runtime and RapidOCR packages, on the order of 84 MB, not by those weights. Tesseract needs no download and remains the fallback.

## Update a copy you already have

From the clone, for example `~/Downloads/archive-workbench`:

```bash
cd ~/Downloads/archive-workbench
git pull
docker compose up --build -d
```

Then open http://localhost:3000. The rebuild is slow the first time because the API image installs the OCR runtime. Later page edits are ordinary.

`AUTH_DISABLED=true` in `.env.example` leaves sign-in off so the workbench still opens. The API logs a warning while that is set.

Europeana and DPLA do nothing until `EUROPEANA_API_KEY` or `DPLA_API_KEY` is set. Internet Archive, the Library of Congress, Wikidata, and OpenAlex work without a key. Gallica is also implemented without a key.

Stop the stack with Ctrl-C, or `docker compose down` from another terminal. `docker compose down -v` also deletes the database volume and the uploaded files.

## Run without Docker

You need Python 3.12, Node 20 or newer, Tesseract, and Postgres 16 with pgvector.

On macOS, with Homebrew:

```bash
brew install python@3.12 node tesseract tesseract-lang postgresql@16 pgvector
```

`tesseract-lang` includes Kannada, Marathi, and Hindi. Confirm with `tesseract --list-langs`. You want `eng`, `kan`, `mar`, and `hin`.

Create a database:

```bash
createdb archive
psql archive -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

If Postgres is on a different user or port, put that in `DATABASE_URL`.

```bash
cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r api/requirements.txt
```

The default PyPI torch wheel is large. On a machine without a GPU you can install the CPU build first:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r api/requirements.txt
```

In four terminals, from the repository root:

```bash
source .venv/bin/activate
export PYTHONPATH=api
alembic -c api/alembic.ini upgrade head
uvicorn archive_workbench.main:app --host 127.0.0.1 --port 8000
```

```bash
source .venv/bin/activate
export PYTHONPATH=api
python -m archive_workbench.worker
```

```bash
cd web
npm install
npm run dev
```

Open http://localhost:3000. The first question or upload also downloads `intfloat/multilingual-e5-small` into the Hugging Face cache if it is not there yet.

`make test` runs the pytest suite. It expects Postgres on `localhost:5432` with the user and database from `.env.example`, and it forces hash embeddings so it does not download the model.

## Using it

1. Upload a PDF or image. A page range such as `1-3, 5` limits what is read. Pick a free OCR engine, or Claude or Gemini once a key is saved. A collection and a document language are stored on the document and can be used as search filters.
2. Wait until the document says Done. While a job runs, the page shows a progress line. The first PP-OCR run names the file it is downloading. The centre pane is the page. Boxes are OCR lines. The transcription is under the image. The three panes can be collapsed or dragged wider. On a tablet they stack.
3. Ask a question in the right-hand pane. A marker like `[1]` is a citation. A document citation moves the viewer to that line. A library citation opens the source.
4. Search your documents (the bar in the header, or Ctrl/Cmd-K) looks through transcriptions, translations, and notes on this computer. A result shows the document, the page, and a short snippet, and opens that place on the page. Filters are collection, language, date uploaded, and engine. Find inside the open document (Ctrl/Cmd-F) highlights matching lines and boxes. Search open libraries is a separate view. It queries catalogues on the internet and does not search your files.
5. Notes are stored on the document. Translate writes a translation onto each page. The translation language is separate from the interface language. Without a model key the translation is marked `[mock translation to …]` and the original text is kept underneath.
6. Export links download DOCX, Markdown, JSON, BibTeX, TEI, a searchable PDF, and plain text.
7. The interface language and light or dark paper are in the header. The choice is remembered in this browser.

## Sign in with Google

Leave `AUTH_DISABLED=true` until you want accounts. Then, in Google Cloud Console:

1. APIs & Services → OAuth consent screen. External is fine for a test. While the app is in testing, add each allowlisted Gmail address as a test user.
2. Credentials → OAuth client ID → Web application.
3. Authorised JavaScript origins: `http://localhost:3000` and, later, `https://<your-domain>`.
4. Authorised redirect URIs, exactly:
   - `http://localhost:3000/api/auth/callback`
   - `https://<your-domain>/api/auth/callback`
5. Copy the client id and secret into `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Set `APP_BASE_URL` to the same origin you open in the browser (`http://localhost:3000` locally). Set `AUTH_DISABLED=false`. Set `ADMIN_EMAILS` (the default is `praveenmaths89@gmail.com`), and optionally `ALLOWED_EMAILS` and `ALLOWED_DOMAINS`.
6. Restart once so the new environment is read: `docker compose up -d`. After that, an admin adds and removes people from Settings without a restart.

Open http://localhost:3000, not http://127.0.0.1:3000, so the cookie and the redirect URI match. Anyone who is not on the list sees “Access not granted”. Sessions are an HTTP-only cookie for 14 days. Sign out is in Settings.

## Tests

```bash
pytest
```

With Docker Postgres already running on port 5432, that is enough. Set `DATABASE_URL` if the database is elsewhere.

The browser smoke test is in `web/tests/smoke.spec.ts`. With the site on port 3000:

```bash
cd web
npx playwright install chromium
npm run test:smoke
```

## What is not in this version

Handwriting is still weak in the free engines. On the British Library minute this was tried against, Tesseract reads printed form labels such as Department and Subject, and misses most of the handwriting. `TESSERACT_LANGS=eng` is cleaner for an English-only page. The default also loads Kannada, Marathi, and Hindi, which can leave stray characters on a Latin page. PP-OCR uses separate English, Devanagari, and Kannada models and is the better free choice for printed text. Vision OCR is there for handwriting, and it needs your own key.

Surya’s code is Apache-2.0, but the weights are a modified OpenRAIL-M licence with a funding and revenue limit, and the CPU path is heavy, so it is not shipped. docTR does not cover these Indic scripts. TrOCR is English handwriting and large. PaddlePaddle itself is a poor fit for arm64 wheels, which is why PP-OCR runs through ONNX Runtime instead. Kraken is not in this release. PP-OCRv6’s single “50 language” model does not cover Kannada or Devanagari.

There is no HathiTrust connector. That API was retired in 2024. NDLI and the Indian Culture portal have no public API. LangGraph, an MCP server, and the Azure deployment are described in `spec.md` under the v2 roadmap and are not built.

The Library of Congress search is slow, often 15 to 40 seconds, and the client waits up to 45 seconds and tries once more. Gallica's SRU endpoint is implemented, but Cloudflare sometimes answers 403 from datacentre addresses. Europeana and DPLA stay quiet until a key is set.

The searchable PDF puts the transcription on the page as an invisible layer. It is not aligned word by word.

## Layout

```
api/archive_workbench/    API, worker, OCR, search, connectors, export
api/alembic/              Postgres migrations
web/                      Next.js workspace
tests/                    pytest
docker-compose.yml
spec.md
```

Do not commit `.env`, the `data/` directory, or PDFs.
