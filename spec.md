# Spec: Document OCR, Conversion & Translation Platform

Status: Draft v0.1
Owner: praveenmaths89@gmail.com

## 1. Purpose

A web application and API that lets a user upload one or many documents (scans, photos, PDFs), extracts the text with OCR, optionally translates it into any language, and exports the result as a Word (`.docx`) or PDF file. The user can bring their own model API key. The system automatically selects the most suitable model for each document based on its complexity, so simple documents are cheap and fast and hard ones get a stronger model.

### Goals
- Single and batch upload with per-file progress and results.
- High-fidelity OCR, including layout (headings, columns, tables) and, where supported, handwriting and historical print.
- Translation to any target language, with an option to keep the original alongside it.
- Export to DOCX and PDF that preserves structure as far as possible.
- Bring-your-own API key (BYOK) for supported model providers.
- Automatic, explainable model routing by document complexity, with manual override.

### Non-goals (v1)
- Real-time or camera streaming OCR.
- Editing documents in the browser beyond correcting extracted text.
- Training or fine-tuning custom models.
- Native mobile apps (the web UI must work on mobile browsers).

### Decisions (resolved)
- **Deployment:** self-hosted / internal, single team. One shared provider key set, set via server config or the Settings page (see section 7); no per-user vault.
- **Primary content:** historical documents and manuscripts (handwriting, degraded scans, old typefaces). Accuracy on these is the top priority and drives routing defaults and the benchmark.
- **Model provider (v1):** Anthropic (Claude) for OCR, translation and research synthesis, because degraded historical material needs strong vision and reading comprehension. A local engine (Tesseract/PaddleOCR) is kept only as the no-key baseline for clean pages. Other providers are post-v1 via the adapter interface.
- **PDF output:** searchable PDF with the original page images and an invisible text layer is the default and primary format (archival use). A reflowed text PDF remains available as an option.
- **Launch languages:** English and major European languages (French, German, Spanish, Italian, Latin), including historical orthography. RTL, Indic and CJK support is post-v1 (fonts and layout still designed not to preclude it).
- **Cost:** no per-page ceiling; accuracy first. The per-job budget cap (FR-23) is optional and off by default.
- **Authentication:** simple shared login or none, relying on the internal network. No per-user accounts in v1.
- **Corrections:** user edits are stored with the producing model and tier for later manual review of thresholds; no automatic tuning.
- **Research sources:** archives, academic and period sources are ranked first, news only as a supplement; domain allow/deny lists are configurable. Research covers the open web only in v1.
- **Web search (v1):** Anthropic's built-in web search tool. A dedicated search API can be added later through the search adapter (e.g. for domain allow-lists).

### Implementation status (v0.2)
| Area | Status |
|---|---|
| Upload (single/multi), validation, per-file rejection | Built |
| OCR via Claude with tier routing and escalation; table rows, figures, marginalia as separate blocks | Built; prompt tuned on sample pages from `Minute Paper`, `Letters ... Elphinstone`, `Doc-7`, `Dharwar` |
| Exports: DOCX (real tables), searchable PDF, TXT, MD, JSON | Built (PDF text layer is page-level, not word-aligned) |
| Review flag | Built, driven by count of `[illegible]` / `[word?]` markers, not model self-reported confidence (which read 0.78-0.88 on well-transcribed pages) |
| Side-by-side viewer, edit and save corrections (originals kept) | Built |
| Page selection: per-file range at upload (`1-5, 8, 12-`), OCR more pages or a single page later, page-status strip; unselected pages cost nothing and can still be previewed | Built |
| Start / Stop: staged upload with Start, Stop after the current page (finished pages kept), resume; Stop on research discards the result (the in-flight call is still billed) | Built |
| Provider failures: billing/auth errors stop the whole run with a plain-language message instead of failing every page | Built |
| Ask bar: question box always visible above both tabs; runs web research and opens the results | Built |
| Web research with citations, depth levels, domain allow-list, follow-up, DOCX/MD export | Built (basic search variant; see FR-46). Runs on the original-language transcript |
| Translation (M2) | **Not built**; research currently reads the untranslated transcript |
| Local OCR tier, deskew, per-word coordinates, Settings page for key, job resume after restart | Not built |
| Research cost | A standard run on one 2-page document used about 250K input tokens (roughly $1 on `claude-opus-5-5`); `MODEL_RESEARCH` is configurable |

## 2. Users and scenarios

| Persona | Scenario |
|---|---|
| Researcher / archivist | Uploads 200 scanned pages of a 19th-century book, wants searchable PDF plus an English DOCX. |
| Business user | Uploads one invoice in German, wants an English PDF. |
| Developer | Calls the REST API with their own key to process documents in a pipeline. |

## 3. Functional requirements

### 3.1 Upload
- FR-1: Accept single or multiple files in one action (drag-and-drop, file picker, API multipart).
- FR-2: Supported inputs: PDF (scanned and born-digital), PNG, JPG/JPEG, TIFF, WEBP, HEIC, DOCX (for translation-only). Multi-page TIFF and PDF are split per page.
- FR-3: Limits (configurable): 50 files per batch, 100 MB per file, 500 pages per file. Violations are reported per file without failing the batch.
- FR-4: Validate by magic bytes, not extension. Reject encrypted or corrupt files with a clear message (offer password prompt for encrypted PDFs).
- FR-5: A batch is a "job"; each file is a "document"; each document has pages.

### 3.2 OCR
- FR-6: Extract text with reading order, plus structure: headings, paragraphs, lists, tables, headers/footers, footnotes, and page numbers.
- FR-7: Pre-process: deskew, denoise, contrast/binarisation, DPI normalisation, orientation detection, and page splitting for two-page spreads.
- FR-8: Detect source language per page automatically; user may override.
- FR-9: Return per-page and per-block confidence scores; flag low-confidence regions.
- FR-10: Handwriting, historical typefaces, and non-Latin scripts are supported via the vision-language model tier (see 3.5).
- FR-11: Born-digital PDFs with a text layer skip OCR and use direct extraction (user can force OCR).

### 3.3 Translation
- FR-12: Target language selectable from a list of all languages the chosen model supports (searchable; ISO 639-1/BCP-47 codes in the API).
- FR-13: Translation modes: `translated only`, `original + translation side by side`, `original then translation (interleaved by paragraph)`.
- FR-14: Preserve structure (headings, tables, lists) and inline formatting during translation; do not translate proper names when flagged, and support a user glossary (term → fixed translation).
- FR-15: Translate in chunks with overlap/context to keep terminology consistent across a document.
- FR-16: Skip translation when the source language equals the target (configurable).

### 3.4 Output
- FR-17: Export formats: DOCX, PDF, and also TXT, Markdown, and JSON (structured, with coordinates and confidence) for developers.
- FR-18: PDF options: (a) searchable PDF with the original image and an invisible text layer (default), (b) reflowed PDF of the extracted/translated text (optional).
- FR-19: DOCX uses real Word styles (Heading 1–6, Normal, Table), embedded images where detected, and page breaks matching source pages (optional).
- FR-20: Download per document, or a ZIP for the entire batch. Output file names derive from the input name plus language code, e.g. `report.fr.docx`.
- FR-21: Right-to-left languages (Arabic, Hebrew, Urdu) and CJK render correctly, with appropriate fonts embedded.

### 3.5 Model configuration and automatic routing
- FR-22: The user can supply an API key and optionally an endpoint/base URL per provider. Providers are accessed through a common adapter interface (see 5.3). v1 adapters: Anthropic (Claude) and a local/open-source OCR engine (e.g. Tesseract or PaddleOCR) that needs no key. OpenAI-compatible endpoints and Google (Gemini) are post-v1.
- FR-23: Modes:
  - **Auto** (default): the router picks the model per document, or per page.
  - **Fixed**: the user pins a model for OCR and/or translation.
  - **Budget cap**: the user sets a maximum cost per job; the router degrades to cheaper models and warns when the cap would be exceeded.
- FR-24: Complexity scoring runs before OCR and produces a tier. Inputs:

  | Signal | How measured |
  |---|---|
  | Image quality | Resolution, blur (Laplacian variance), noise, skew, contrast |
  | Layout complexity | Number of columns, tables, figures, mixed orientation (via a lightweight layout detector) |
  | Content type | Printed vs. handwritten vs. mixed (classifier) |
  | Script / language | Latin vs. complex scripts (Arabic, Devanagari, CJK), historical orthography |
  | Text layer | Present and trustworthy vs. absent |
  | Size | Page count, text density |

- FR-25: Tiers and default routing. Model IDs are configuration, not hard-coded; defaults below use the Claude family and must be confirmed against the benchmark:

  | Tier | Typical document | OCR route | Translation route |
  |---|---|---|---|
  | 1 – Simple | Clean printed single column, or born-digital | Local OCR engine / direct text extraction | Haiku-class (`claude-haiku-5-5`) |
  | 2 – Moderate | Printed with tables, multi-column, average scans | Sonnet-class vision (`claude-sonnet-5-5`) | Sonnet-class |
  | 3 – Complex | Handwriting, degraded or historical print, dense tables, non-Latin scripts | Most capable available model (`claude-opus-5-5` or `claude-fable-5-1`) | Same as OCR route |

  Because the corpus is mostly historical, the scorer's default thresholds are biased upward: handwriting, degraded scans and pre-20th-century typefaces go straight to Tier 3 without a Tier 1 attempt.

- FR-26: Routing is per page, so one mixed document can use different tiers. Pages are re-routed upward automatically when confidence falls below a threshold (default 0.85): escalate once to the next tier, then flag for review.
- FR-27: Routing is explainable: the result shows the tier, score, signals, chosen model, cost and tokens used for every page. Users can re-run a page with a different model.
- FR-28: If the user supplies only one key or provider, the router restricts itself to that provider's models and says so.
- FR-29: Fall back to another configured model on provider errors, rate limits, or content refusals, with bounded retries and exponential backoff.

### 3.6 Review and correction
- FR-30: Side-by-side viewer: source page image with highlighted blocks and the extracted text. Low-confidence blocks are highlighted.
- FR-31: Users can edit extracted text before translation/export; edits are kept and re-export is possible without re-running OCR.

### 3.7 Job management
- FR-32: Asynchronous processing with a job queue; the UI shows status per document and page (`queued`, `preprocessing`, `ocr`, `translating`, `exporting`, `done`, `failed`).
- FR-33: Partial success: failed documents do not fail the batch; they can be retried individually.
- FR-34: Job history with retention (default 30 days), after which files are deleted.
- FR-35: Optional webhook or email notification on completion.

### 3.8 Contextual research (web search and Q&A)

After OCR and translation, the user can ask the system to research the document: find related incidents, background, people, places, events and any other information relevant to the content or to a question the user asks about it.

- FR-36: **Research panel** on each document (and on a whole batch), with two entry points:
  - **Auto-brief**: one click generates a context report from the document alone (key entities, dates, places, events, claims worth verifying, and related incidents).
  - **Ask**: a free-text question, e.g. "What happened at this event?", "Are there similar incidents?", "Who is the person named on page 3?". The answer must draw on both the document and the web.
- FR-37: **Entity and topic extraction**: before searching, the system extracts entities (people, organisations, places, dates, events, legal or technical terms) and the main topics from the translated and original text, and shows them to the user. Users can select, deselect or add entities to steer the search.
- FR-38: **Query planning**: the system turns the document context and the user's question into several search queries (including queries in the document's original language and in the target language, and with historical place or name variants), runs them, and iterates when results are thin (bounded, default max 3 rounds and 20 sources).
- FR-39: **Search depth modes**: `quick` (single round, few sources), `standard` (default), and `deep` (multi-round, cross-checking, longer report). The cost and time estimate is shown before a deep run.
- FR-40: **Source handling**: fetch and read the pages, not only the snippets; deduplicate; record URL, title, publisher, publication date and retrieval time. Prefer reliable sources (official, archival, academic, established news) and show a source-type label. Allow/deny lists of domains are configurable by the user.
- FR-41: **Cited answers**: every factual statement in the research output carries an inline citation to a source, and statements taken from the document itself cite the page and block. Claims that rest on a single source or on conflicting sources are marked as such. If nothing reliable is found, the system says so instead of guessing.
- FR-42: **Related incidents view**: a timeline or list of related events with date, location, short description, how it relates to the document, and a link to the source. Users can filter by date range, place and relevance.
- FR-43: **Follow-up conversation**: the user can continue asking follow-up questions in a chat bound to the document; context (document text, prior findings, sources) is retained for the session.
- FR-44: **Language handling**: the user's question may be in any language; searches run in the languages that are most likely to hold relevant sources; the final answer is written in the user's chosen language.
- FR-45: **Output**: the research report can be viewed in the UI and exported to DOCX, PDF or Markdown, either as a separate file or appended to the translated document as an "Annex: Context and related information", with a bibliography.
- FR-46: **Provider choice**: the search layer is an adapter (see 5.3). Supported options: a model's built-in web search tool (when the user's chosen provider offers it) or a separate search API (e.g. Brave, Bing, Google Programmable Search, Tavily, SerpAPI) with the user's own key. The reasoning/synthesis model follows the same Auto/Fixed routing rules as 3.5; research questions are routed by question complexity (a simple lookup uses a small model, multi-source synthesis uses the strongest).
- FR-47: **Privacy controls**: web search sends text derived from the document to external services. The system must (a) show the exact queries that were run alongside every result (implemented; approving queries *before* they run is not possible with a single server-side search call and would need a separate planning step, so it is deferred), (b) never send the full document text to a search engine, only short extracted queries, (c) support redaction of selected entities (e.g. personal names) from queries, and (d) be fully disabled in "local only" mode or by an organisation setting.
- FR-48: **Safety and quality**: treat retrieved web content as untrusted data, never as instructions (guard against prompt injection in fetched pages); do not follow or fetch links that are unsafe or require login; show a freshness warning when sources are old for time-sensitive questions; flag possible speculation, rumours or unverified claims; respect robots.txt and site terms.
- FR-49: **Sensitive content**: for documents that appear to concern living private individuals, medical, legal or similar sensitive material, the system shows a notice and does not run an automatic broad search about a named private individual unless the user explicitly confirms and has a legitimate purpose.
- FR-50: **Cost and limits**: search calls, pages fetched and tokens used are tracked per research run and count toward the job budget cap (FR-23). Quotas per user and per day are configurable.

## 4. API (v1 sketch)

All endpoints are under `/api/v1`, authenticated with a bearer token.

| Method | Path | Description |
|---|---|---|
| POST | `/jobs` | Create a job. Multipart: `files[]`, plus JSON `options`. Returns `job_id`. |
| GET | `/jobs/{id}` | Job status, per-document and per-page progress, cost so far. |
| GET | `/jobs/{id}/documents/{doc_id}` | Document metadata, routing decisions, confidence. |
| GET | `/jobs/{id}/documents/{doc_id}/download?format=docx\|pdf\|txt\|md\|json` | Download output. |
| GET | `/jobs/{id}/download?format=...` | ZIP of all documents. |
| POST | `/jobs/{id}/documents/{doc_id}/pages/{n}/rerun` | Re-run a page with a specific model. |
| PUT | `/providers/{provider}` | Set or update the provider key (admin only, write-only; never returned). |
| GET | `/models` | Models available to the user's keys, with capabilities and prices. |
| POST | `/jobs/{id}/documents/{doc_id}/research` | Start a research run. Body: `question` (optional), `depth`, `entities`, `languages`, `domain_allow`/`domain_deny`, `output`. Returns `research_id`. |
| GET | `/research/{id}` | Status, extracted entities, queries run, sources, answer with citations, related-incidents list. |
| POST | `/research/{id}/messages` | Follow-up question in the research chat. |
| GET | `/research/{id}/download?format=docx\|pdf\|md\|json` | Export the research report. |
| DELETE | `/jobs/{id}` | Delete job and all files, including research runs. |

Example `options`:

```json
{
  "ocr": { "source_language": "auto", "force_ocr": false },
  "translation": {
    "target_language": "fr",
    "mode": "side_by_side",
    "glossary": [{ "source": "Bodleian", "target": "Bodleian" }]
  },
  "output": { "formats": ["docx", "pdf"], "pdf_type": "searchable" },
  "model": {
    "mode": "auto",
    "max_cost_usd": 5.0,
    "pin": { "ocr": null, "translation": null }
  }
}
```

## 5. Architecture

### 5.1 Components
```
Web UI ──► API service ──► Object storage (originals, page images, outputs)
              │
              ├──► Queue ──► Workers:
              │               1. Ingest / split / pre-process
              │               2. Complexity scorer + router
              │               3. OCR (adapter)
              │               4. Structure builder
              │               5. Translator (adapter)
              │               6. Exporter (DOCX / PDF / others)
              │               7. Research agent (entity extraction → query
              │                  planning → web search → fetch/read → synthesis
              │                  with citations)
              └──► Database (jobs, documents, pages, routing logs, usage)
```

### 5.2 Processing pipeline (per page)
1. Render page to image at 300 DPI; run pre-processing.
2. Compute complexity signals and tier.
3. Router selects the OCR model.
4. OCR returns structured blocks (type, text, bbox, confidence).
5. If confidence < threshold, escalate and repeat step 4 once.
6. Assemble a document-level intermediate representation (IR): ordered blocks with styles and tables.
7. Translate the IR text nodes in context-aware chunks; reattach to the structure.
8. Export from the IR to the requested formats.

The IR (JSON) is the single source of truth between stages, which keeps OCR, translation and export independently testable and lets users re-export without re-running earlier stages.

### 5.3 Model adapter interface
```
OcrModel.extract(page_image, hints) -> Blocks
TranslationModel.translate(blocks, source, target, glossary, context) -> Blocks
ModelInfo { id, provider, supports_vision, languages, max_tokens, price_in, price_out, tier }
SearchProvider.search(query, lang, date_range, domains) -> [Result{url, title, snippet, date}]
PageFetcher.fetch(url) -> CleanText{text, title, published, retrieved_at}
ResearchAgent.run(ir, question, depth, options) -> Report{answer, citations, incidents[], queries[]}
```
New providers are added by implementing the adapter and registering `ModelInfo`. The model-to-tier mapping lives in configuration so it can be updated as models change.

### 5.4 Suggested tech stack (adjustable)
- Backend: Python (FastAPI), Celery or RQ workers, Redis queue, PostgreSQL, S3-compatible storage.
- Preprocessing/OCR: OpenCV, PyMuPDF, Tesseract/PaddleOCR for the local tier.
- Export: `python-docx` for DOCX; ReportLab or WeasyPrint for reflowed PDF; `ocrmypdf`-style text-layer injection for searchable PDF.
- Frontend: React or Next.js with a PDF/image viewer.

## 6. Non-functional requirements

| Area | Requirement |
|---|---|
| Performance | Tier 1 page ≤ 3 s; Tier 3 page ≤ 30 s end-to-end excluding queue time. 100-page job finishes in under 15 min with default concurrency. |
| Scalability | Workers scale horizontally; per-provider concurrency limits and rate-limit aware scheduling. |
| Accuracy targets | Printed Latin text ≥ 98% character accuracy on benchmark set; handwriting and historical text tracked separately. Measured by CER/WER on a held-out set. |
| Reliability | Idempotent stages, per-page checkpoints, resume after worker crash. |
| Privacy | See section 7. |
| Accessibility | WCAG 2.1 AA for the UI; DOCX/PDF output tagged for accessibility where possible. |
| Observability | Structured logs, per-stage metrics, cost and token tracking per job, tracing by job id. |
| Localisation | UI strings externalised for translation. |

## 7. Security and privacy

- API keys can be set in server configuration (environment variables) or entered in the Settings page (your original "give the API key" requirement). Keys entered in the UI are stored encrypted on the server, write-only (never shown again or returned by the API), redacted from logs, and used only server-side. One shared key set per deployment; a per-user key vault is out of scope for v1.
- Uploaded files and outputs are encrypted at rest and in transit (TLS 1.2+), isolated per user, and deleted after the retention window or on request.
- Documents are sent only to the providers the user has configured. The UI tells the user clearly when a document will leave the system (any non-local model) and offers a "local only" mode.
- No document content is used for training by this platform; provider data policies are shown next to each provider.
- Malware scanning of uploads; sandboxed rendering of PDFs and Office files; zip-bomb and decompression limits.
- Rate limiting and per-user quotas; audit log of key changes and deletions.
- Research (3.8): search queries are minimal and optionally redacted; fetched web content is sandboxed and treated as untrusted (prompt-injection defence); search-provider keys are handled like model keys; research outputs are stored with the job and deleted with it.
- Copyright/legal: the user is responsible for having rights to process uploaded material; this is stated in the terms.

## 8. Error handling

| Case | Behaviour |
|---|---|
| Unreadable or blank page | Mark page `failed: unreadable`, continue with the rest. |
| Provider key invalid or out of quota | Pause affected pages, notify the user, offer to switch model or retry. |
| Unsupported language for the chosen model | Suggest another model or route automatically if in Auto mode. |
| Budget cap reached | Stop paid calls, finish the remaining pages with the local tier if possible, report clearly. |
| Output too large | Split ZIP, or offer per-document download. |

## 9. Testing and evaluation

- Unit tests per stage using IR fixtures.
- Golden-set benchmark: 200+ pages across printed, tabular, multi-column, handwritten, historical, degraded and non-Latin scripts, with ground truth. Report CER/WER, table-structure accuracy, and translation quality (human review plus an automated metric such as COMET/chrF).
- Router evaluation: compare Auto against always-cheapest and always-best on cost and accuracy; the target is within 1% accuracy of always-best at ≥ 40% lower cost on a mixed set.
- Export validation: open generated DOCX/PDF in Word, LibreOffice and common PDF readers; automated checks for fonts, RTL and page counts.
- Research evaluation: a set of documents with questions and reference answers; measure citation accuracy (every claim supported by its cited source), hallucination rate, relevance of related incidents, and behaviour when no sources exist. Include prompt-injection test pages.
- Load test: 50 concurrent jobs of 100 pages each.

## 10. Milestones

| Phase | Scope |
|---|---|
| M1 – Core (3–4 wks) | Single and multi upload, preprocessing, local OCR, one cloud model adapter, IR, DOCX/PDF export, job status UI. |
| M2 – Translation (2–3 wks) | Translation stage, language picker, side-by-side modes, glossary, RTL/CJK output. |
| M3 – Routing (3 wks) | Complexity scorer, tiers, confidence-based escalation, explainability UI, Settings page for API key entry, budget cap. |
| M4 – Research (3–4 wks) | Entity extraction, query planning, search/fetch adapters, cited answers, related-incidents view, follow-up chat, report export, privacy controls. |
| M5 – Review and API (2–3 wks) | Review/edit viewer, public REST API, webhooks, ZIP export, retention jobs. |
| M6 – Hardening (2 wks) | Benchmarking, load testing, security review, accessibility audit. |

## 11. Open questions

All v1 questions are resolved (see Decisions in section 1). Items deferred past v1:

- Automatic tuning of routing thresholds from user corrections.
- Searching previously processed documents or an external catalogue during research.
- SSO, per-user accounts and a per-user key vault.
- Launch languages beyond English and major European (RTL, Indic, CJK).
