from __future__ import annotations

import io
import json
import secrets
import shutil
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import export, ingest, research as research_mod, store
from .ranges import parse_pages
from .adapters import get_adapter
from .config import ROOT, settings
from .ir import DocumentIR
from .pipeline import FatalProviderError, process_document, process_page

API = "/api/v1"


class Auth(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    app_password: str = ""  # empty = no login (internal network)


auth_cfg = Auth()
basic = HTTPBasic(auto_error=False)


def require_login(creds: HTTPBasicCredentials | None = Depends(basic)):
    if not auth_cfg.app_password:
        return
    if not creds or not secrets.compare_digest(creds.password, auth_cfg.app_password):
        raise HTTPException(401, "login required", headers={"WWW-Authenticate": "Basic"})


app = FastAPI(title="Historical Document OCR", dependencies=[Depends(require_login)])
pool = ThreadPoolExecutor(max_workers=settings.workers)
FORMATS = {"docx", "pdf", "txt", "md", "json"}
SAFE_EXT = {"pdf", "png", "jpg", "jpeg", "tif", "tiff", "webp"}


def doc_dir(job_id: str, doc_id: str) -> Path:
    return settings.data_dir / "jobs" / job_id / doc_id


def load_ir(job_id: str, doc_id: str) -> DocumentIR:
    p = doc_dir(job_id, doc_id) / "ir.json"
    if not p.exists():
        raise HTTPException(409, "document has no results yet")
    return DocumentIR.model_validate_json(p.read_text())


busy: set[str] = set()
stop_requests: set[str] = set()  # doc ids the user asked to stop
busy_lock = threading.Lock()


def run_document(job_id: str, doc_id: str, filename: str, src: Path, kind: str, options: dict,
                 pages: list[int] | None = None, redo: bool = False):
    """OCR `pages` (None = all). Safe to call again later to add more pages to the same document."""
    with busy_lock:
        if doc_id in busy:
            return
        if doc_id in stop_requests:  # stopped while still queued
            stop_requests.discard(doc_id)
            store.update_document(doc_id, status="stopped")
            return
        busy.add(doc_id)
    try:
        store.update_document(doc_id, status="processing", error=None)
        total = ingest.page_count(src, kind)
        store.update_document(doc_id, total_pages=total)

        def progress(done: int, selected: int):
            store.update_document(doc_id, done_pages=done, selected_pages=selected)

        stop_requests.discard(doc_id)
        process_document(get_adapter(), doc_id, filename, src, kind, doc_dir(job_id, doc_id), total, pages,
                         on_progress=progress, force_ocr=options.get("force_ocr", False),
                         pin_model=options.get("pin_model"), redo=redo,
                         should_stop=lambda: doc_id in stop_requests)
        ir = load_ir(job_id, doc_id)
        failed = sum(p.status == "failed" for p in ir.pages)
        if doc_id in stop_requests:
            store.update_document(doc_id, status="stopped")
        else:
            store.update_document(doc_id, status="done" if not failed else "done_with_errors")
    except FatalProviderError as e:
        store.update_document(doc_id, status="failed", error=str(e))
    except Exception as e:
        store.update_document(doc_id, status="failed", error=f"{type(e).__name__}: {e}")
    finally:
        stop_requests.discard(doc_id)
        with busy_lock:
            busy.discard(doc_id)


@app.post(f"{API}/jobs")
async def create_job(files: List[UploadFile] = File(...), options: str = Form("{}")):
    try:
        opts = json.loads(options)
    except json.JSONDecodeError:
        raise HTTPException(400, "options must be JSON")
    if len(files) > settings.max_files_per_job:
        raise HTTPException(400, f"max {settings.max_files_per_job} files per job")
    job_id = store.create_job(json.dumps(opts))
    results = []
    for f in files:
        name = Path(f.filename or "upload").name
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        doc_id = store.add_document(job_id, name, "unknown")
        d = doc_dir(job_id, doc_id)
        d.mkdir(parents=True, exist_ok=True)
        src = d / f"source.{ext if ext in SAFE_EXT else 'bin'}"
        size = 0
        with src.open("wb") as out:
            while chunk := await f.read(1 << 20):
                size += len(chunk)
                if size > settings.max_file_mb * 1024 * 1024:
                    break
                out.write(chunk)
        try:
            if size > settings.max_file_mb * 1024 * 1024:
                raise ingest.IngestError(f"file exceeds {settings.max_file_mb} MB")
            kind = ingest.detect_kind(src)
            total = ingest.page_count(src, kind)
            spec = (opts.get("pages_by_file") or {}).get(name, opts.get("pages"))
            try:
                pages = parse_pages(spec, total)
            except ValueError as ve:
                raise ingest.IngestError(f"page range: {ve} (file has {total} pages)")
            if len(pages or range(total)) > settings.max_pages_per_file:
                raise ingest.IngestError(f"more than {settings.max_pages_per_file} pages selected")
        except Exception as e:
            store.update_document(doc_id, status="rejected", error=str(e))
            src.unlink(missing_ok=True)
            results.append({"doc_id": doc_id, "filename": name, "status": "rejected", "error": str(e)})
            continue
        store.update_document(doc_id, kind=kind)
        store.update_document(doc_id, total_pages=total, selected_pages=len(pages) if pages else total)
        pool.submit(run_document, job_id, doc_id, name, src, kind, opts, pages)
        results.append({"doc_id": doc_id, "filename": name, "status": "queued", "pages": len(pages) if pages else total,
                        "total_pages": total})
    return {"job_id": job_id, "documents": results}


@app.get(f"{API}/jobs")
def list_jobs():
    return store.list_jobs()


@app.get(f"{API}/jobs/{{job_id}}")
def job_status(job_id: str):
    job, docs = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {"job_id": job_id, "created": job["created"], "documents": docs}


@app.get(f"{API}/jobs/{{job_id}}/documents/{{doc_id}}")
def document_detail(job_id: str, doc_id: str):
    ir = load_ir(job_id, doc_id)
    return {"doc_id": doc_id, "filename": ir.filename, "pages": [
        {"number": p.number, "status": p.status, "source": p.source, "language": p.language,
         "confidence": p.confidence, "flagged": p.flagged, "uncertain": p.uncertain,
         "edited": p.edited, "routing": p.routing,
         "tokens": {"in": p.input_tokens, "out": p.output_tokens}, "error": p.error,
         "signals": p.signals, "text": p.text,
         "blocks": [{**b.model_dump(), "rows": b.table_rows() if b.type == "table" else None}
                    for b in p.blocks]} for p in ir.pages]}


@app.get(f"{API}/jobs/{{job_id}}/documents/{{doc_id}}/pages/{{n}}/image")
def page_image(job_id: str, doc_id: str, n: int):
    """The page image. Pages that were not OCR'd are rendered on demand so they can still be previewed."""
    ir = load_ir(job_id, doc_id)
    if not 1 <= n <= len(ir.pages):
        raise HTTPException(404, "page image not found")
    page = ir.pages[n - 1]
    if page.image_path and Path(page.image_path).exists():
        return FileResponse(page.image_path, media_type="image/jpeg")
    doc, src = store.get_document(doc_id), next(doc_dir(job_id, doc_id).glob("source.*"), None)
    if not doc or not src:
        raise HTTPException(404, "page image not found")
    cache = doc_dir(job_id, doc_id) / f"preview_{n:04d}.jpg"
    if not cache.exists():
        img, _ = ingest.get_page(src, doc["kind"], n)
        cache.write_bytes(ingest.to_jpeg(img, max_edge=1600, quality=80))
    return FileResponse(cache, media_type="image/jpeg")


@app.post(f"{API}/jobs/{{job_id}}/documents/{{doc_id}}/stop")
def stop_document(job_id: str, doc_id: str):
    """Stop OCR after the page currently being read. Finished pages are kept; Start resumes the rest."""
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "document not found")
    if doc["status"] not in ("queued", "processing"):
        return {"status": doc["status"], "note": "not running"}
    stop_requests.add(doc_id)
    if doc["status"] == "queued" and doc_id not in busy:  # still waiting for a worker
        store.update_document(doc_id, status="stopped")
    return {"status": "stopping"}


class OcrReq(BaseModel):
    pages: Optional[str] = None  # e.g. "6-10, 14"; empty = all remaining
    redo: bool = False  # re-run pages that are already done
    model: Optional[str] = None


@app.post(f"{API}/jobs/{{job_id}}/documents/{{doc_id}}/ocr")
def ocr_more(job_id: str, doc_id: str, req: OcrReq):
    """Run OCR on more pages of an already-uploaded document."""
    doc = store.get_document(doc_id)
    src = next(doc_dir(job_id, doc_id).glob("source.*"), None)
    if not doc or not src:
        raise HTTPException(404, "document not found")
    if doc_id in busy or doc["status"] in ("queued", "processing"):
        raise HTTPException(409, "this document is still being processed - stop it first")
    try:
        pages = parse_pages(req.pages, doc["total_pages"])
    except ValueError as e:
        raise HTTPException(400, f"page range: {e} (file has {doc['total_pages']} pages)")
    ir = load_ir(job_id, doc_id)
    wanted = pages or [p.number for p in ir.pages]
    todo = wanted if req.redo else [n for n in wanted if ir.pages[n - 1].status != "done"]
    if not todo:
        return {"status": "nothing_to_do", "pages": 0}
    store.update_document(doc_id, status="queued")
    pool.submit(run_document, job_id, doc_id, doc["filename"], src, doc["kind"],
                {"pin_model": req.model}, todo, req.redo)
    return {"status": "queued", "pages": len(todo)}


class BlockIn(BaseModel):
    type: str = "paragraph"
    text: str = ""
    rows: Optional[List[List[str]]] = None


class PageEdit(BaseModel):
    blocks: List[BlockIn]


@app.put(f"{API}/jobs/{{job_id}}/documents/{{doc_id}}/pages/{{n}}")
def edit_page(job_id: str, doc_id: str, n: int, body: PageEdit):
    """Save corrected text. The model's original output is kept for later threshold review."""
    from .ir import Block
    from .pipeline import count_uncertain
    ir = load_ir(job_id, doc_id)
    if not 1 <= n <= len(ir.pages):
        raise HTTPException(404, "page not found")
    page = ir.pages[n - 1]
    if page.original_blocks is None:
        page.original_blocks = page.blocks
    page.blocks = [Block(type=b.type, text=b.text, rows=b.rows, confidence=1.0)
                   for b in body.blocks if b.text.strip() or b.rows]
    page.edited = True
    page.uncertain = count_uncertain(page)
    page.flagged = False
    (doc_dir(job_id, doc_id) / "ir.json").write_text(ir.model_dump_json(indent=1))
    return {"page": n, "edited": True}


# ---------- research ----------

class ResearchReq(BaseModel):
    question: Optional[str] = None
    depth: str = "standard"
    pages: Optional[List[int]] = None  # default: all pages
    allowed_domains: Optional[List[str]] = None
    blocked_domains: Optional[List[str]] = None
    language: Optional[str] = None
    follow_up_of: Optional[str] = None  # research_id whose report is given as context


def research_dir(job_id: str, doc_id: str) -> Path:
    return doc_dir(job_id, doc_id) / "research"


def run_research_job(job_id: str, doc_id: str, rid: str, req: ResearchReq):
    path = research_dir(job_id, doc_id) / f"{rid}.json"
    rec = json.loads(path.read_text())

    def stopped() -> bool:
        return json.loads(path.read_text()).get("status") == "stopped"
    try:
        ir = load_ir(job_id, doc_id)
        pages = [p for p in ir.pages if not req.pages or p.number in req.pages]
        text = "\n\n".join(f"[Page {p.number}]\n{p.text}" for p in pages if p.text.strip())
        if not text.strip():
            raise ValueError("document has no transcribed text to research")
        prev = None
        if req.follow_up_of:
            pp = research_dir(job_id, doc_id) / f"{req.follow_up_of}.json"
            if pp.exists():
                prev = json.loads(pp.read_text()).get("answer_md")
        res = research_mod.run_research(ir.filename, text, req.question, req.depth, req.allowed_domains,
                                        req.blocked_domains, req.language, prev)
        if stopped():
            return
        rec.update(status="done", answer_md=res.answer_md, queries=res.queries,
                   sources=[s.__dict__ for s in res.sources], consulted=[s.__dict__ for s in res.consulted],
                   tokens={"in": res.input_tokens, "out": res.output_tokens},
                   searches=res.search_requests, stop_reason=res.stop_reason)
    except Exception as e:
        if stopped():
            return
        from .pipeline import fatal_message
        rec.update(status="failed", error=fatal_message(e) or f"{type(e).__name__}: {e}")
    path.write_text(json.dumps(rec, indent=1))


@app.post(f"{API}/jobs/{{job_id}}/documents/{{doc_id}}/research")
def start_research(job_id: str, doc_id: str, req: ResearchReq):
    load_ir(job_id, doc_id)
    if not settings.anthropic_api_key or settings.use_mock:
        raise HTTPException(400, "research needs an Anthropic API key (not available in mock mode)")
    if req.depth not in research_mod.DEPTH:
        raise HTTPException(400, f"depth must be one of {sorted(research_mod.DEPTH)}")
    if req.allowed_domains and req.blocked_domains:
        raise HTTPException(400, "use allowed_domains or blocked_domains, not both")
    rid = store.new_id()
    d = research_dir(job_id, doc_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{rid}.json").write_text(json.dumps({"id": rid, "status": "running", "question": req.question,
                                                "depth": req.depth, "doc_id": doc_id, "job_id": job_id}))
    pool.submit(run_research_job, job_id, doc_id, rid, req)
    return {"research_id": rid, "status": "running"}


def find_research(rid: str) -> tuple[Path, dict]:
    for p in (settings.data_dir / "jobs").glob(f"*/*/research/{rid}.json"):
        return p, json.loads(p.read_text())
    raise HTTPException(404, "research not found")


@app.post(f"{API}/research/{{rid}}/stop")
def stop_research(rid: str):
    """Stop waiting for a research run. The search call already in flight finishes server-side
    (and is billed), but its result is discarded."""
    path, rec = find_research(rid)
    if rec.get("status") == "running":
        rec.update(status="stopped")
        path.write_text(json.dumps(rec, indent=1))
    return {"status": rec["status"]}


@app.get(f"{API}/research/{{rid}}")
def get_research(rid: str):
    return find_research(rid)[1]


@app.get(f"{API}/jobs/{{job_id}}/documents/{{doc_id}}/research")
def list_research(job_id: str, doc_id: str):
    d = research_dir(job_id, doc_id)
    recs = [json.loads(p.read_text()) for p in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime)] if d.exists() else []
    return [{k: r.get(k) for k in ("id", "status", "question", "depth")} for r in recs]


def report_markdown(rec: dict) -> str:
    out = [rec.get("answer_md", "")]
    if rec.get("sources"):
        out += ["", "## Sources"] + [f"{s['n']}. [{s['title']}]({s['url']})" for s in rec["sources"]]
    if rec.get("queries"):
        out += ["", "## Searches run"] + [f"- {q}" for q in rec["queries"]]
    return "\n".join(out)


@app.get(f"{API}/research/{{rid}}/download")
def download_research(rid: str, format: str = "md"):
    _, rec = find_research(rid)
    if rec.get("status") != "done":
        raise HTTPException(409, "research not finished")
    md = report_markdown(rec)
    if format == "docx":
        return Response(export.markdown_to_docx(md, "Research report"),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="research_{rid}.docx"'})
    if format == "md":
        return Response(md.encode(), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="research_{rid}.md"'})
    raise HTTPException(400, "format must be md or docx")


def render(ir: DocumentIR, fmt: str) -> tuple[bytes, str]:
    if fmt == "docx":
        return export.to_docx(ir), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if fmt == "pdf":
        return export.to_searchable_pdf(ir), "application/pdf"
    if fmt == "txt":
        return export.to_txt(ir).encode(), "text/plain; charset=utf-8"
    if fmt == "md":
        return export.to_md(ir).encode(), "text/markdown; charset=utf-8"
    return export.to_json(ir).encode(), "application/json"


@app.get(f"{API}/jobs/{{job_id}}/documents/{{doc_id}}/download")
def download(job_id: str, doc_id: str, format: str = "docx"):
    if format not in FORMATS:
        raise HTTPException(400, f"format must be one of {sorted(FORMATS)}")
    ir = load_ir(job_id, doc_id)
    data, mime = render(ir, format)
    stem = Path(ir.filename).stem
    return Response(data, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{stem}.{format}"'})


@app.get(f"{API}/jobs/{{job_id}}/download")
def download_zip(job_id: str, format: str = "docx"):
    if format not in FORMATS:
        raise HTTPException(400, f"format must be one of {sorted(FORMATS)}")
    job, docs = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for d in docs:
            if (doc_dir(job_id, d["id"]) / "ir.json").exists():
                ir = load_ir(job_id, d["id"])
                z.writestr(f"{Path(ir.filename).stem}.{format}", render(ir, format)[0])
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="job_{job_id}.zip"'})


class Rerun(BaseModel):
    model: Optional[str] = None


@app.post(f"{API}/jobs/{{job_id}}/documents/{{doc_id}}/pages/{{n}}/rerun")
def rerun_page(job_id: str, doc_id: str, n: int, body: Rerun):
    ir = load_ir(job_id, doc_id)
    doc = store.get_document(doc_id)
    src = next(doc_dir(job_id, doc_id).glob("source.*"), None)
    if not doc or not src or not 1 <= n <= len(ir.pages):
        raise HTTPException(404, "page not found")
    img, text = ingest.get_page(src, doc["kind"], n)
    page = process_page(get_adapter(), n, img, text, doc_dir(job_id, doc_id),
                        force_ocr=True, pin_model=body.model)
    ir.pages[n - 1] = page
    (doc_dir(job_id, doc_id) / "ir.json").write_text(ir.model_dump_json(indent=1))
    return {"page": n, "status": page.status, "routing": page.routing, "confidence": page.confidence}


@app.get(f"{API}/models")
def models():
    return {"tiers": {t: settings.model_for_tier(t) for t in (1, 2, 3)},
            "api_key_configured": bool(settings.anthropic_api_key),
            "mode": "mock" if (settings.use_mock or not settings.anthropic_api_key) else "claude"}


@app.delete(f"{API}/jobs/{{job_id}}")
def delete_job(job_id: str):
    shutil.rmtree(settings.data_dir / "jobs" / job_id, ignore_errors=True)
    with store.db() as c:
        c.execute("DELETE FROM documents WHERE job_id=?", (job_id,))
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    return {"deleted": job_id}


@app.get("/", response_class=HTMLResponse)
def index():
    # no-store: the UI changes often and a cached old copy hides new controls
    return FileResponse(Path(__file__).parent / "static" / "index.html", headers={"Cache-Control": "no-store"})
