# Archive Workbench

Version 1.0
Author: Praveen D Chougale
Contact: praveenmaths89@gmail.com
Licence: Apache-2.0
Status: specification for the first open-source release

Archive Workbench is an open-source research workbench for archaeology and history. A researcher uploads historical documents — handwriting, old print, colonial Indian archives such as British Library records on Kittur and Dharwar — and works from the page image, the transcription, and the sources that sit around them.

The prototype (v0.2) was a FastAPI app that sent page images to Claude, stored jobs in SQLite, and served a single HTML page. This document keeps the behaviour from that prototype that is still right, and replaces the parts that do not fit a local-first workbench.

It runs on one machine first. Cloud deployment is a later step, described under the v2 roadmap.

## 1. What a researcher can do

- Upload scans and PDFs, including multi-page files, and choose which pages to read.
- Get OCR, with the text tied to regions on the page, plus a short explanation of the page.
- Ask questions. Answers cite the document (page and region) and, when they use them, web or library sources. A check after the answer drops or flags any claim that has no citation.
- Search open libraries for related documents.
- Translate a transcription into Indian languages (and other languages the configured model can handle).
- Keep notes on a document.
- Export DOCX, Markdown, JSON, BibTeX, and TEI. The searchable PDF and plain text from v0.2 stay available.

Documents and API keys stay on the machine that runs the app. Nothing is uploaded to a hosted Archive Workbench service, because there isn't one in v1.

## 2. What stays from v0.2

These behaviours were built and checked against sample pages (a British Library Minute Paper, Elphinstone letters, and Dharwar material). They remain requirements.

- Single and batch upload. A bad file is rejected on its own and does not fail the batch.
- File types: PDF, PNG, JPEG, TIFF, WEBP. Type is detected from magic bytes, not the extension. Encrypted or corrupt files get a clear error. Limits, configurable: 50 files per batch, 100 MB per file, 500 pages per file.
- Page selection at upload (`1-5, 8, 12-`) and again later. Unselected pages are not sent to an OCR engine. They can still be previewed.
- Start and stop. Stopping finishes the page in progress and keeps finished pages. The rest can be run later.
- A provider failure that will hit every page (bad key, no credit) stops the run with a plain message. Finished pages are kept.
- The intermediate representation is still the contract between stages: ordered blocks with a type (heading, paragraph, list item, table, figure, marginalia, other), text, optional table rows, and a confidence. Tables export as real Word tables and as Markdown pipe tables.
- Reading order is preserved. Two columns are read one column at a time. Unreadable words are marked `[illegible]`; uncertain readings are marked `[word?]`. Scanner footers and watermarks are omitted.
- The review flag is driven by those markers (three or more) or by a very low confidence (under 0.6). A self-reported confidence around 0.8 does not flag a page.
- The user can correct a page. The model's original blocks are kept.
- Born-digital PDFs with a usable text layer skip OCR. The user can force OCR.
- Blank pages are detected and not sent to a model.
- Complexity signals (blur, contrast, ink density, background unevenness) and tier routing remain for vision OCR. Historical scans are biased to the strongest configured vision model. If confidence is under 0.85 the page is escalated once.
- Research treats the document and fetched pages as data, not as instructions.
- Optional shared password. Empty password means no login, which matches an internal or single-user install.

Translation was specified in v0.2 and not built. It is in v1, and the first targets are Indian languages rather than only English and major European languages. Web research no longer depends on Anthropic's built-in search tool. Library connectors and the model's own knowledge, grounded by retrieval, take that role. A general web-search API can still be added behind the same connector interface.

## 3. Architecture

```
Browser (Next.js) ──► API (FastAPI) ──► Postgres 16
                         │                 pgvector + full-text search
                         │                 job queue (SKIP LOCKED)
                         └── files on disk (page images, originals)

Worker process ──► same Postgres queue
               ├── Tesseract OCR (default)
               ├── vision OCR through LiteLLM (only with a user key)
               ├── embeddings
               ├── translate
               └── read → retrieve → answer → verify
```

| Piece | Choice |
|---|---|
| API | FastAPI, Python |
| Database | Postgres 16, image `pgvector/pgvector:pg16` |
| Retrieval | Hybrid: Postgres full-text search plus pgvector cosine similarity |
| Queue | Rows in Postgres, claimed with `FOR UPDATE SKIP LOCKED`. No Redis |
| Worker | Separate process, same codebase as the API |
| UI | Next.js (App Router, TypeScript), OpenSeadragon for the page |
| OCR default | Tesseract, offline, `eng+kan+mar+hin` |
| OCR optional | Claude or Gemini vision when the user sets a key. Kraken is not in v1 |
| Models | LiteLLM used as a library. Anthropic, Gemini, OpenAI, Ollama |
| Agent | Plain Python. LangGraph is deferred to v2 |
| Embeddings | `intfloat/multilingual-e5-small` (384 dimensions) via sentence-transformers, unless an API embedding model is configured |
| Run | `docker compose up` starts `db`, `api`, `worker`, and `web` |

The API process serves HTTP and writes jobs. The worker claims jobs. OCR, embedding, explanation, translation, and question answering run in the worker so a long page does not tie up a request.

## 4. OCR

Default engine is Tesseract. It needs no key and no network. The Docker image installs traineddata for English, Kannada, Marathi, and Hindi. The language string is configurable (`TESSERACT_LANGS`, default `eng+kan+mar+hin`). Word boxes from Tesseract are grouped into lines. Each line is a region with a pixel bounding box. Those boxes are the overlay on the page viewer.

Anuvaad's printed and handwriting models are an optional later engine for Indic pages, not the default. NLTM/Bhashini and Lipikar are the other Indic OCR projects to look at. There is no verified project under the name "IndicOCR"; that name is not used here.

When `OCR_ENGINE` is `claude` or `gemini` and a key is set, the worker sends the page image through LiteLLM and reuses the v0.2 transcription prompt (exact spelling, `[illegible]` / `[word?]`, separate blocks for labels, handwriting, stamps, tables, figures, and marginalia). The prompt also asks for a normalised box per block so the overlay still has somewhere to land. If a box is missing, the block is placed in a vertical band in reading order. Vision OCR is skipped when no key is set; the worker uses Tesseract and records that it did so.

Surya is not a default engine. Its weights are OpenRAIL-M and the licence limits commercial use above a revenue threshold. A Surya plug-in may be added later, off by default, for people who accept that licence.

Kraken is a possible later engine for handwritten lines. It is not required for v1.

After OCR, the worker writes a short explanation of the document. With no model key this is extractive: the first lines of the transcription and the page count. With a key, a short model call writes the explanation and must quote the transcription rather than invent context.

## 5. Embeddings and hybrid search

Each region is packed into a chunk of roughly 500 characters, staying inside a page. Chunks are embedded with `intfloat/multilingual-e5-small` (prefix `query:` for the question and `passage:` for the text, as that model expects). The vector column is `vector(384)`.

An API embedding model may be set with `EMBEDDING_PROVIDER=api`. It must return 384 dimensions (for example an OpenAI model called with a dimensions parameter). A mismatch is an error, not a silent truncate.

Search inside the workbench combines, per chunk:

- a full-text rank (`websearch_to_tsquery` on the `simple` configuration, so Indian-language text is not dropped by an English stemmer)
- a cosine similarity on the embedding

The two ranks are min-max scaled and added with equal weight. Results point at a document, a page, and a region.

`EMBEDDING_PROVIDER=hash` exists for tests. It is not the default.

## 6. Questions and the verifier

Asking a question enqueues an `ask` job. The worker runs four steps, in order, in ordinary Python functions:

1. **Read.** Load the question and the document title. Do not send the whole corpus.
2. **Retrieve.** Hybrid search over that document's chunks (top 6). Then a short library search (Internet Archive, OpenAlex, Wikidata) so the answer can cite an external source when one is relevant. Library calls are skipped when the question is clearly about the page alone and the document hits are strong; they are always available from the library tab.
3. **Answer.** With a model key, LiteLLM is asked to answer only from the numbered passages and library hits, with a `[n]` marker after every factual sentence. Without a key, the worker writes an extractive answer: each sentence quotes a retrieved passage or names a library hit and carries that item's marker. It does not pretend a model was called.
4. **Verify.** A cheap check, no second model call. Split the answer into sentences. A sentence that states a fact must contain a `[n]` marker whose `n` is one of the retrieved sources. Anything else is removed. The reply tells the user when sentences were removed. A sentence that only says the document does not contain the answer is kept. Markers that point past the source list are stripped. If nothing remains, the user gets a clear "no supported answer" line.

Citations in the API are objects, not just numbers:

- `kind: "document"` with `document_id`, `page`, `region_id`, and a short quote
- `kind: "library"` with `source`, `title`, and `url`

The UI turns a document citation into a jump: the viewer opens that page and highlights the region.

## 7. Library connectors

Every connector implements one method: `search(query, limit) -> list[Hit]`. A hit has `source`, `title`, `url`, `creators`, `date`, and `description`.

| Connector | v1 | Notes |
|---|---|---|
| Internet Archive | Live, no key | `advancedsearch.php` JSON API |
| Library of Congress | Live, no key | JSON search. Hard cap of 20 requests per minute |
| Wikidata | Live, no key | `wbsearchentities` |
| OpenAlex | Live, no key | works search. A descriptive User-Agent is sent |
| Gallica | Live, no key | SRU `searchRetrieve`. If the endpoint fails, that source returns an error and the others still return |
| Europeana | Behind `EUROPEANA_API_KEY` | Without a key the source reports `not_configured` |
| DPLA | Behind `DPLA_API_KEY` | Without a key the source reports `not_configured` |

Responses are cached in Postgres, keyed by connector and normalised query, for 24 hours. Rate limits are enforced in the worker before the HTTP call. Connectors run in the API process for the library tab (they are short) and share the same cache and limiter as the ask job.

The HathiTrust Data API was retired in 2024. It is not a connector. NDLI and the Indian Culture portal have no public API. They are not connectors. A person can still paste a URL into notes.

Trove (National Library of Australia) is a possible later connector. It is not in v1.

## 8. Translation

`POST /api/documents/{id}/translate` with a BCP-47 or English language name (`hi`, `kn`, `mr`, `ta`, Hindi, Kannada, …) enqueues a job. The worker translates each transcribed page. With a key, LiteLLM does it and is told to keep proper names and `[illegible]` markers. Without a key, each page is returned with a `[mock translation to {lang}]` banner and the original text, so the UI and the export can be tried offline.

The translated text is stored per page and included in DOCX, Markdown, and TEI exports when present.

## 9. Notes

A document has many notes. Each note is a text body and a timestamp. Notes are not sent to a model unless the user asks a question that explicitly includes them (v1 does not include them automatically).

## 10. Data model

Postgres. Identifiers are UUIDs. Timestamps are `timestamptz`.

**documents.** id, filename, title, kind (`pdf` or `image`), status (`queued`, `processing`, `done`, `done_with_errors`, `failed`, `rejected`, `stopped`), page_count, selected_pages, language, explanation, error, source_path, created_at.

**pages.** id, document_id, number, status (`skipped`, `pending`, `done`, `failed`), image_path, width, height, text, translation, translation_language, ocr_engine, language, confidence, flagged, uncertain, edited, error. A generated `tsv` (`to_tsvector('simple', text)`) with a GIN index.

**regions.** id, document_id, page_id, idx, type, text, x, y, w, h (pixels on the stored JPEG), confidence.

**chunks.** id, document_id, page_id, region_id, page_number, text, embedding `vector(384)`, tsv GIN index, HNSW index on embedding (`vector_cosine_ops`).

**notes.** id, document_id, body, created_at, updated_at.

**messages.** id, document_id, role (`user` or `assistant`), content, citations (jsonb), dropped (jsonb), created_at.

**jobs.** id, kind (`ocr`, `embed`, `explain`, `translate`, `ask`), document_id, payload (jsonb), status (`queued`, `running`, `done`, `failed`), run_after, locked_at, locked_by, attempts, max_attempts, error, result (jsonb), created_at, updated_at.

Claim:

```sql
UPDATE jobs SET status = 'running', locked_at = now(), locked_by = :worker,
                attempts = attempts + 1, updated_at = now()
WHERE id = (
  SELECT id FROM jobs
  WHERE status = 'queued' AND run_after <= now() AND attempts < max_attempts
  ORDER BY created_at
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING *;
```

Failed jobs with attempts left are requeued with a short delay. A job that hits `max_attempts` stays `failed`.

**library_cache.** connector, query, payload (jsonb), fetched_at. Primary key (connector, query).

Schema changes go through Alembic. The API runs `upgrade head` on startup.

Files live under `DATA_DIR` (`/data` in Compose): `documents/{id}/source.*` and `documents/{id}/page_0001.jpg`. The database stores paths. `data/` is gitignored.

## 11. HTTP API

Prefix `/api`. No `/api/v1` prefix in this release; the v0.2 routes were a prototype surface. JSON unless noted. Errors use FastAPI's `{"detail": "..."}`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Database up, OCR engine, whether a model key is set, embedding provider |
| POST | `/api/documents` | Multipart `files[]`, optional form field `options` (JSON: `pages`, `pages_by_file`, `force_ocr`, `ocr_engine`) |
| GET | `/api/documents` | List, newest first |
| GET | `/api/documents/{id}` | Document, pages (without image bytes), regions, notes count, latest jobs |
| DELETE | `/api/documents/{id}` | Delete the row, chunks, files |
| POST | `/api/documents/{id}/stop` | Stop OCR after the current page |
| POST | `/api/documents/{id}/ocr` | Queue OCR for more pages. Body: `pages`, `redo`, `ocr_engine` |
| GET | `/api/documents/{id}/pages/{n}` | One page, its regions, text, translation |
| GET | `/api/documents/{id}/pages/{n}/image` | JPEG. Unread pages are rendered on demand |
| PUT | `/api/documents/{id}/pages/{n}` | Replace blocks. Body: `{blocks: [{type, text, rows?}]}`. Originals are kept |
| GET | `/api/documents/{id}/notes` | List notes |
| POST | `/api/documents/{id}/notes` | `{body}` |
| DELETE | `/api/documents/{id}/notes/{note_id}` | Delete one note |
| GET | `/api/documents/{id}/messages` | Chat so far |
| POST | `/api/documents/{id}/ask` | `{question}` → `{message_id, job_id}` |
| POST | `/api/documents/{id}/translate` | `{language}` → `{job_id}` |
| GET | `/api/documents/{id}/export?format=` | `docx`, `md`, `json`, `bibtex`, `tei`, `txt`, `pdf` |
| GET | `/api/search?q=` | Hybrid search across documents. Optional `document_id` |
| GET | `/api/library/search?q=&sources=` | `sources` is a comma list. Default: the four no-key connectors plus Gallica |
| GET | `/api/jobs/{id}` | Job status and result |

Upload still accepts the v0.2 page-range syntax. The response lists each file as `queued` or `rejected` with the reason.

Export filenames come from the upload name: `minute-paper.docx`, and so on. BibTeX uses `@unpublished` with the title, the transcription date, and a note that the file was produced locally. TEI is TEI P5: a header with the title and licence of the export (the export, not the source document), and one `div` per page containing the regions as `p` or `table` elements. Coordinates are recorded as `facs` attributes in pixel units of the JPEG.

The searchable PDF is the v0.2 behaviour: the page image plus an invisible text layer. Boxes are still line-level, not word-aligned in the PDF text layer.

## 12. Interface

One Next.js app. Two views, switched from the header: **Workspace** and **Library search**.

### Workspace

Three panes, left to right.

**Library.** The documents on this machine. Each row shows the filename, status, and page count. An upload control (button and drag-and-drop) adds files. A page-range field applies to the next upload. Selecting a document loads it in the other two panes. Status text is plain: queued, reading, done, failed.

**Page.** OpenSeadragon. Previous and next page, and a page field. OCR regions are drawn as boxes over the image. The box for the citation the user last clicked stays highlighted. A button toggles the overlay. The transcription for the current page sits under the image (or beside it when the window is wide): one block per region, in order. Low-confidence lines are marked. The explanation sits at the top of this pane in two or three sentences.

**Chat.** The question field, the thread, and the notes. Assistant messages render `[n]` as buttons. A document citation moves the viewer to that page and region. A library citation is a link that opens in a new tab. Notes are a list with an add box.

The panes have landmarks (`nav`, `main`, the chat as a complementary region). Every control has a visible name. Focus is visible. Text and the paper background meet WCAG AA contrast. The layout stacks vertically under 960px wide: library, page, chat.

### Library search

A query box, checkboxes for each connector, and a result list: title, source, date, creators, a short description, and the URL. A source that is not configured (Europeana, DPLA without a key) is shown as such, not as an empty result. Errors from one source do not hide the others.

### Look

Quiet. Off-white paper, near-black ink, a single dark-red accent for the current selection and for citation buttons. Serif for the document title and the transcription, sans-serif for the chrome. No dashboard cards, no gradient hero, no marketing slogans on the working screen. The header is the name "Archive Workbench" and the two views.

## 13. Non-functional requirements

| Area | Requirement |
|---|---|
| Privacy | Originals, page images, transcriptions, notes, and chats stay in local Postgres and `DATA_DIR`. Keys live in `.env` or the environment, never in the database, never in the UI after save, never in logs. The health endpoint reports only whether a key is set |
| Local only | With no `LLM_API_KEY`, OCR is Tesseract, answers are extractive, translation is the mock banner. No call is made to a model vendor |
| Leaving the machine | Vision OCR, model answers, model translation, and API embeddings send data out. The health endpoint shows the mode. Library search sends the query only, not the document |
| Auth | Optional `APP_PASSWORD` (HTTP basic), as in v0.2. No accounts, no SSO in v1 |
| Retention | No automatic deletion. The user deletes a document when they want it gone |
| Accessibility | WCAG 2.1 AA for the chrome and the transcription. The page image has a text alternative (the transcription) |
| Performance | A two-page scan finishes OCR without a model in well under a minute on a laptop, not counting the first embedding-model download. Library search returns or fails per source within 20 seconds |
| Reliability | The worker can be killed and started again. Jobs left `running` longer than 15 minutes are returned to the queue. Page images are written before the page is marked done |
| Ports | Web on 3000, API on 8000, Postgres on 5432 |

## 14. Configuration

See `.env.example`. The names that matter:

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | local Compose URL | Postgres |
| `DATA_DIR` | `/data` in Compose, `./data` without | Files |
| `LLM_API_KEY` | empty | Any key LiteLLM will accept for `LLM_MODEL` |
| `LLM_MODEL` | `anthropic/claude-sonnet-4-5` | LiteLLM model id. Examples: `gemini/gemini-2.0-flash`, `openai/gpt-4o-mini`, `ollama/llama3.2` |
| `LLM_API_BASE` | empty | For Ollama or a proxy |
| `OCR_ENGINE` | `tesseract` | `tesseract`, `claude`, or `gemini` |
| `TESSERACT_LANGS` | `eng+kan+mar+hin` | Passed to Tesseract |
| `EMBEDDING_PROVIDER` | `local` | `local`, `api`, or `hash` |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-small` | Local model name, or the API model when provider is `api` |
| `EUROPEANA_API_KEY` | empty | Europeana |
| `DPLA_API_KEY` | empty | DPLA |
| `APP_PASSWORD` | empty | Optional basic auth |

`ANTHROPIC_API_KEY` is still read if `LLM_API_KEY` is empty, so a v0.2 `.env` keeps working.

## 15. Repository layout

```
api/archive_workbench/     Python package (API, worker, OCR, agent, connectors, export)
api/alembic/               migrations
api/Dockerfile
web/                       Next.js app
tests/                     pytest
docker-compose.yml
Makefile
.env.example
spec.md
README.md
```

The v0.2 modules (`pipeline`, `export`, `ingest`, `ir`, `signals`, `ranges`, the Claude OCR prompt) live under `api/archive_workbench/` and are called by the worker. They are not a second application.

## 16. Acceptance criteria

A fresh clone, with Docker Desktop on an Apple Silicon Mac, passes the following. The same checks are what this repository's tests and the maintainer's run cover.

1. `cp .env.example .env` then `docker compose up --build` brings up db, api, worker, and web. `http://localhost:3000` loads the workspace.
2. `GET /api/health` reports a database connection and `llm: false` when no key is set.
3. Uploading a scanned PDF queues an OCR job. The worker runs Tesseract. The document reaches `done` or `done_with_errors`. Page text is non-empty for a page that has writing. Regions have boxes.
4. Asking a question returns an assistant message whose factual sentences each carry a citation the verifier accepted. At least one citation is a document page and region when the transcription contains relevant text. Clicking it in the UI moves the viewer.
5. Library search for a known term (for example `Kittur`) returns hits from Internet Archive or OpenAlex or Wikidata or the Library of Congress, without a key.
6. Europeana and DPLA report `not_configured` when their keys are empty.
7. Adding a note and reloading the document shows the note.
8. Translate to `hi` stores a translation. Without a key it is marked mock.
9. Export DOCX, Markdown, JSON, BibTeX, and TEI. DOCX opens as a zip (`PK` magic). TEI is well-formed XML.
10. `pytest` passes against the Compose database.
11. No PDF, no `data/`, and no `.env` are in git.

## 17. Tests

- pytest for page ranges, export, the verifier, connector parsing (HTTP mocked), the queue claim (SKIP LOCKED), hybrid search, and the upload → OCR → ask → export path. OCR in that path uses Tesseract on a small synthetic image, or the sample minute paper when it is present outside the repo.
- A Playwright smoke test loads the workspace, checks the three panes and the library view, and does not require a model key.

## 18. How to run

Docker is the supported path. The README is the procedure: copy `.env.example` to `.env`, `docker compose up --build`, open `http://localhost:3000`.

Without Docker: install Postgres 16 with pgvector, Tesseract with the four language packs, Python 3.12, and Node 20 or newer. Create the database, set `DATABASE_URL` and `DATA_DIR` in `.env`, run Alembic, start the API, start the worker, and run the Next.js dev server. The README lists the commands.

The first local embedding run downloads `multilingual-e5-small` (a few hundred megabytes) into the Hugging Face cache.

## 19. Corrections recorded here

- The HathiTrust Data API was retired in 2024. Do not integrate it.
- NDLI and the Indian Culture portal have no public API.
- "IndicOCR" is not a verified project name. Indic OCR options to track are NLTM/Bhashini, Lipikar, and Anuvaad.
- Surya's weights are OpenRAIL-M with a revenue limit. Optional plug-in only, not a default and not shipped in v1.

## 20. v2 roadmap

Not scheduled, and not required for the acceptance criteria above.

- LangGraph (or a similar graph runtime) for the agent, once the plain pipeline has been used on real research sessions
- An MCP server so other tools can call the workbench
- Langfuse tracing
- A reranker in front of the hybrid results
- IndicTrans2 for translation that does not need a commercial key
- A notebook and a book-writer on top of notes and cited answers
- Trove connector
- Surya as an opt-in OCR plug-in
- Mirador and IIIF, for manifests from libraries that publish them
- Timeline and map views of entities
- SSO and accounts
- Azure deployment: Container Apps, Azure Database for PostgreSQL, Blob storage, Key Vault
- Modi script OCR

## 21. Out of scope for v1

Real-time camera OCR, training models, a mobile app, per-user accounts, automatic threshold tuning, word-aligned PDF text layers, and editing the scan itself.
