# Archive Workbench

Archive Workbench is a local research workbench for archaeology and history. You upload a scanned document, read it next to the page, ask questions that come back with citations, search open libraries, translate the transcription, and keep notes.

It is meant to run on your own machine. Documents stay in Postgres and a data folder on that machine. Model keys stay in `.env`. With no key, OCR is Tesseract and answers are quoted from the transcription instead of being written by a model.

Author: Praveen D Chougale. Licence: Apache-2.0. The design is in `spec.md`.

## Run with Docker

This is the setup to use on a Mac with Docker Desktop, including an Apple Silicon Mac. Docker Desktop includes Compose.

```bash
cp .env.example .env
docker compose up --build
```

Then open http://localhost:3000.

The first build is slow. The API image installs Tesseract (English, Kannada, Marathi, Hindi) and downloads the small multilingual embedding model. Later starts are ordinary.

Leave `LLM_API_KEY` empty in `.env` if you do not want any page or question sent to a model vendor. Fill it in, and set `LLM_MODEL` to a LiteLLM model id, when you want Claude, Gemini, OpenAI, or a local Ollama server (`LLM_API_BASE=http://host.docker.internal:11434` and a model such as `ollama/llama3.2`).

`OCR_ENGINE=claude` or `gemini` uses vision OCR when a key is set. Without a key the worker uses Tesseract and says so on the page.

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

1. Upload a PDF or image. A page range such as `1-3, 5` limits what is read.
2. Wait until the document says Done. The centre pane is the page. Boxes are OCR lines. The transcription is under the image.
3. Ask a question in the right-hand pane. A brown marker like `[1]` is a citation. A document citation moves the viewer to that line. A library citation opens the source.
4. Library search, in the header, queries the open catalogues. One source failing does not hide the others.
5. Notes are stored on the document. Translate writes a translation onto each page. The language box takes a code such as `hi`, `kn`, or `mr`. Without a model key the translation is marked `[mock translation to …]` and the original text is kept underneath.
6. Export links download DOCX, Markdown, JSON, BibTeX, TEI, a searchable PDF, and plain text.

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

Handwriting will often be poor in Tesseract. On the British Library minute this was tried against, Tesseract reads printed form labels such as Department and Subject, and misses most of the handwriting. `TESSERACT_LANGS=eng` is cleaner for an English-only page. The default also loads Kannada, Marathi, and Hindi, which can leave stray characters on a Latin page. Vision OCR is there for handwriting, and it needs your own key. Kraken and Surya are not included. Surya's weights are OpenRAIL-M with a revenue limit, so it stays an optional plug-in for later rather than a default.

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
