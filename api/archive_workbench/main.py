"""HTTP API for Archive Workbench."""
from __future__ import annotations

import json
import logging
import shutil
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from . import auth, export
from .config import settings
from .connectors import DEFAULT_SOURCES
from .connectors.base import search_libraries
from .db import engine, session as new_session
from .ingest import IngestError, detect_kind, get_page, page_count, to_jpeg
from .migrate import run_migrations
from .models import AccessEntry, AppSetting, Document, Job, Message, Note, Page, Region
from .ocr_ppocr import model_status
from .pipeline import build_ir, document_dir, page_image_path
from .queue import enqueue
from .ranges import parse_pages
from .runtime import ENGINES, current, load_runtime, mask_secret, put_setting, use_runtime
from .search import workspace_search

log = logging.getLogger("api")

API = "/api"
FORMATS = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "json": "application/json",
    "bibtex": "application/x-bibtex",
    "tei": "application/tei+xml; charset=utf-8",
}
SAFE_EXT = {"pdf", "png", "jpg", "jpeg", "tif", "tiff", "webp"}
PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/callback",
    "/api/auth/logout",
    "/api/auth/me",
}


def get_db():
    db = new_session()
    try:
        yield db
    finally:
        db.close()


def require_user(request: Request, db: Session = Depends(get_db)):
    if request.url.path in PUBLIC_PATHS:
        return auth.read_user(request, db)
    user = auth.read_user(request, db)
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    return user


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    run_migrations()
    if settings.auth_disabled:
        message = (
            "AUTH_DISABLED is set. Google sign-in is off. "
            "Anyone who can open this computer can use the workbench."
        )
        print(message, file=sys.stderr, flush=True)
        logging.getLogger("uvicorn.error").warning(message)
    db = new_session()
    try:
        auth.seed_access(db)
    finally:
        db.close()
    yield


app = FastAPI(title="Archive Workbench", dependencies=[Depends(require_user)], lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _doc_or_404(db: Session, document_id: uuid.UUID) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    return doc


def _page_json(page: Page) -> dict:
    return {
        "id": str(page.id),
        "number": page.number,
        "status": page.status,
        "width": page.width,
        "height": page.height,
        "text": page.text,
        "translation": page.translation,
        "translation_language": page.translation_language,
        "ocr_engine": page.ocr_engine,
        "language": page.language,
        "confidence": page.confidence,
        "flagged": page.flagged,
        "uncertain": page.uncertain,
        "edited": page.edited,
        "error": page.error,
    }


def _region_json(region: Region, number: int) -> dict:
    return {
        "id": str(region.id),
        "page_id": str(region.page_id),
        "page_number": number,
        "idx": region.idx,
        "type": region.type,
        "text": region.text,
        "x": region.x,
        "y": region.y,
        "w": region.w,
        "h": region.h,
        "confidence": region.confidence,
    }


def _document_json(db: Session, doc: Document, detail: bool = False) -> dict:
    payload = {
        "id": str(doc.id),
        "filename": doc.filename,
        "title": doc.title,
        "kind": doc.kind,
        "status": doc.status,
        "page_count": doc.page_count,
        "selected_pages": doc.selected_pages,
        "language": doc.language,
        "collection": doc.collection,
        "ocr_engine": doc.ocr_engine,
        "progress": doc.progress,
        "explanation": doc.explanation,
        "error": doc.error,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }
    if not detail:
        return payload
    pages = db.scalars(select(Page).where(Page.document_id == doc.id).order_by(Page.number)).all()
    numbers = {page.id: page.number for page in pages}
    regions = db.scalars(select(Region).where(Region.document_id == doc.id)).all()
    notes = db.scalars(select(Note).where(Note.document_id == doc.id).order_by(Note.created_at)).all()
    jobs = db.scalars(select(Job).where(Job.document_id == doc.id).order_by(Job.created_at.desc())).all()
    payload["pages"] = [_page_json(page) for page in pages]
    payload["regions"] = [_region_json(region, numbers.get(region.page_id, 0)) for region in regions]
    payload["notes"] = [_note_json(note) for note in notes]
    payload["jobs"] = [
        {"id": str(job.id), "kind": job.kind, "status": job.status, "error": job.error}
        for job in jobs[:12]
    ]
    return payload


def _note_json(note: Note) -> dict:
    return {
        "id": str(note.id),
        "body": note.body,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
    }


@app.get(f"{API}/health")
def health():
    database = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        database = False
    runtime = current()
    try:
        with new_session() as db:
            runtime = load_runtime(db)
    except Exception:
        pass
    return {
        "database": database,
        "ocr_engine": runtime.ocr_engine,
        "llm": runtime.configured,
        "embedding": settings.embedding_provider,
        "auth_disabled": settings.auth_disabled,
        "max_file_mb": settings.max_file_mb,
    }


@app.get(f"{API}/documents")
def list_documents(db: Session = Depends(get_db)):
    docs = db.scalars(select(Document).order_by(Document.created_at.desc())).all()
    return [_document_json(db, doc) for doc in docs]


@app.post(f"{API}/documents")
async def upload_documents(
    files: list[UploadFile] = File(...),
    options: str = Form("{}"),
    db: Session = Depends(get_db),
):
    try:
        opts = json.loads(options or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "options must be JSON")
    if len(files) > settings.max_files_per_job:
        raise HTTPException(400, f"max {settings.max_files_per_job} files per batch")
    results = []
    for upload in files:
        name = Path(upload.filename or "upload").name
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        doc = Document(filename=name, title=Path(name).stem, status="queued")
        db.add(doc)
        db.flush()
        folder = document_dir(doc.id)
        src = folder / f"source.{ext if ext in SAFE_EXT else 'bin'}"
        size = 0
        with src.open("wb") as out:
            while chunk := await upload.read(1 << 20):
                size += len(chunk)
                if size > settings.max_file_mb * 1024 * 1024:
                    break
                out.write(chunk)
        try:
            if size > settings.max_file_mb * 1024 * 1024:
                raise IngestError(
                    f"file is larger than {settings.max_file_mb} MB. "
                    "Choose a smaller file, or raise MAX_FILE_MB and restart the workbench."
                )
            kind = detect_kind(src)
            total = page_count(src, kind)
            spec = (opts.get("pages_by_file") or {}).get(name, opts.get("pages"))
            pages = parse_pages(spec, total)
            chosen = pages or list(range(1, total + 1))
            if len(chosen) > settings.max_pages_per_file:
                raise IngestError(f"more than {settings.max_pages_per_file} pages selected")
        except Exception as exc:
            doc.status = "rejected"
            doc.error = str(exc)
            src.unlink(missing_ok=True)
            db.commit()
            results.append({"id": str(doc.id), "filename": name, "status": "rejected", "error": str(exc)})
            continue
        doc.kind = kind
        doc.source_path = str(src)
        doc.page_count = total
        doc.selected_pages = len(chosen)
        engine = opts.get("ocr_engine")
        doc.ocr_engine = engine if engine in ENGINES else None
        doc.collection = (opts.get("collection") or "").strip() or None
        if opts.get("language"):
            doc.language = str(opts.get("language"))[:40]
        for number in range(1, total + 1):
            status = "pending" if number in chosen else "skipped"
            db.add(Page(document_id=doc.id, number=number, status=status))
        enqueue(db, "ocr", {
            "pages": chosen,
            "force_ocr": bool(opts.get("force_ocr")),
            "ocr_engine": opts.get("ocr_engine"),
        }, doc.id)
        db.commit()
        results.append({
            "id": str(doc.id),
            "filename": name,
            "status": "queued",
            "pages": len(chosen),
            "total_pages": total,
        })
    return {"documents": results}


@app.get(f"{API}/documents/{{document_id}}")
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    return _document_json(db, _doc_or_404(db, document_id), detail=True)


@app.delete(f"{API}/documents/{{document_id}}")
def delete_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = _doc_or_404(db, document_id)
    shutil.rmtree(settings.data_dir / "documents" / str(doc.id), ignore_errors=True)
    db.delete(doc)
    db.commit()
    return {"deleted": str(document_id)}


@app.post(f"{API}/documents/{{document_id}}/stop")
def stop_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = _doc_or_404(db, document_id)
    doc.stop_requested = True
    if doc.status == "queued":
        for job in db.scalars(select(Job).where(Job.document_id == doc.id, Job.status == "queued")).all():
            job.status = "failed"
            job.error = "stopped before it started"
        doc.status = "stopped"
    db.commit()
    return {"status": doc.status}


class OcrBody(BaseModel):
    pages: str | list[int] | None = None
    redo: bool = False
    ocr_engine: str | None = None


@app.post(f"{API}/documents/{{document_id}}/ocr")
def ocr_more(document_id: uuid.UUID, body: OcrBody, db: Session = Depends(get_db)):
    doc = _doc_or_404(db, document_id)
    if doc.status in ("queued", "processing"):
        raise HTTPException(409, "this document is still being read")
    try:
        pages = parse_pages(body.pages, doc.page_count)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    doc.stop_requested = False
    doc.status = "queued"
    doc.error = None
    enqueue(db, "ocr", {
        "pages": pages,
        "redo": body.redo,
        "ocr_engine": body.ocr_engine,
        "force_ocr": True if body.redo else False,
    }, doc.id)
    db.commit()
    return {"status": "queued", "job": "ocr"}


@app.get(f"{API}/documents/{{document_id}}/pages/{{number}}")
def get_page_detail(document_id: uuid.UUID, number: int, db: Session = Depends(get_db)):
    doc = _doc_or_404(db, document_id)
    page = db.scalars(select(Page).where(Page.document_id == doc.id, Page.number == number)).first()
    if page is None:
        raise HTTPException(404, "page not found")
    regions = db.scalars(select(Region).where(Region.page_id == page.id).order_by(Region.idx)).all()
    payload = _page_json(page)
    payload["regions"] = [_region_json(region, number) for region in regions]
    return payload


@app.get(f"{API}/documents/{{document_id}}/pages/{{number}}/image")
def get_page_image(document_id: uuid.UUID, number: int, db: Session = Depends(get_db)):
    doc = _doc_or_404(db, document_id)
    page = db.scalars(select(Page).where(Page.document_id == doc.id, Page.number == number)).first()
    if page is None or not (1 <= number <= doc.page_count):
        raise HTTPException(404, "page not found")
    path = Path(page.image_path) if page.image_path else page_image_path(doc.id, number)
    if not path.exists():
        src = Path(doc.source_path) if doc.source_path else None
        if src is None or not src.exists():
            raise HTTPException(404, "page image not found")
        img, _text = get_page(src, doc.kind, number)
        path = page_image_path(doc.id, number)
        path.write_bytes(to_jpeg(img, max_edge=1600, quality=80))
        page.image_path = str(path)
        page.width = page.width or int(img.shape[1])
        page.height = page.height or int(img.shape[0])
        db.commit()
    return FileResponse(path, media_type="image/jpeg")


class BlockIn(BaseModel):
    type: str = "paragraph"
    text: str = ""
    rows: list[list[str]] | None = None


class PageEdit(BaseModel):
    blocks: list[BlockIn]


@app.put(f"{API}/documents/{{document_id}}/pages/{{number}}")
def edit_page(document_id: uuid.UUID, number: int, body: PageEdit, db: Session = Depends(get_db)):
    doc = _doc_or_404(db, document_id)
    page = db.scalars(select(Page).where(Page.document_id == doc.id, Page.number == number)).first()
    if page is None:
        raise HTTPException(404, "page not found")
    existing = db.scalars(select(Region).where(Region.page_id == page.id).order_by(Region.idx)).all()
    if page.original_regions is None:
        page.original_regions = [
            {"type": region.type, "text": region.text, "x": region.x, "y": region.y,
             "w": region.w, "h": region.h, "confidence": region.confidence}
            for region in existing
        ]
    from .ocr import count_uncertain, needs_review
    kept = [block for block in body.blocks if block.text.strip() or block.rows]
    db.execute(delete(Region).where(Region.page_id == page.id))
    db.flush()
    lines = []
    for index, block in enumerate(kept):
        text = block.text
        if block.rows and not text.strip():
            text = "\n".join("\t".join(row) for row in block.rows)
        previous = existing[index] if index < len(existing) else None
        db.add(Region(
            document_id=doc.id,
            page_id=page.id,
            idx=index,
            type=block.type,
            text=text,
            x=previous.x if previous else 0,
            y=previous.y if previous else index * 40,
            w=previous.w if previous else (page.width or 100),
            h=previous.h if previous else 32,
            confidence=1.0,
        ))
        lines.append(text)
    page.text = "\n".join(lines)
    page.edited = True
    page.uncertain = count_uncertain(page.text)
    page.flagged = needs_review(page.uncertain, 1.0)
    page.status = "done"
    enqueue(db, "embed", {}, doc.id)
    db.commit()
    return {"page": number, "edited": True}


@app.get(f"{API}/documents/{{document_id}}/notes")
def list_notes(document_id: uuid.UUID, db: Session = Depends(get_db)):
    _doc_or_404(db, document_id)
    notes = db.scalars(select(Note).where(Note.document_id == document_id).order_by(Note.created_at)).all()
    return [_note_json(note) for note in notes]


class NoteIn(BaseModel):
    body: str


@app.post(f"{API}/documents/{{document_id}}/notes")
def add_note(document_id: uuid.UUID, body: NoteIn, db: Session = Depends(get_db)):
    _doc_or_404(db, document_id)
    if not body.body.strip():
        raise HTTPException(400, "note is empty")
    note = Note(document_id=document_id, body=body.body.strip())
    db.add(note)
    db.commit()
    db.refresh(note)
    return _note_json(note)


@app.delete(f"{API}/documents/{{document_id}}/notes/{{note_id}}")
def delete_note(document_id: uuid.UUID, note_id: uuid.UUID, db: Session = Depends(get_db)):
    note = db.get(Note, note_id)
    if note is None or note.document_id != document_id:
        raise HTTPException(404, "note not found")
    db.delete(note)
    db.commit()
    return {"deleted": str(note_id)}


@app.get(f"{API}/documents/{{document_id}}/messages")
def list_messages(document_id: uuid.UUID, db: Session = Depends(get_db)):
    _doc_or_404(db, document_id)
    rows = db.scalars(select(Message).where(Message.document_id == document_id).order_by(Message.created_at)).all()
    return [
        {
            "id": str(row.id),
            "role": row.role,
            "content": row.content,
            "citations": row.citations or [],
            "dropped": row.dropped or [],
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


class AskBody(BaseModel):
    question: str


@app.post(f"{API}/documents/{{document_id}}/ask")
def ask(document_id: uuid.UUID, body: AskBody, db: Session = Depends(get_db)):
    doc = _doc_or_404(db, document_id)
    if doc.status not in ("done", "done_with_errors", "stopped"):
        raise HTTPException(409, "the document is still being read")
    if not body.question.strip():
        raise HTTPException(400, "question is empty")
    message = Message(document_id=doc.id, role="user", content=body.question.strip())
    db.add(message)
    job = enqueue(db, "ask", {"question": body.question.strip()}, doc.id)
    db.commit()
    return {"message_id": str(message.id), "job_id": str(job.id)}


class TranslateBody(BaseModel):
    language: str


@app.post(f"{API}/documents/{{document_id}}/translate")
def translate(document_id: uuid.UUID, body: TranslateBody, db: Session = Depends(get_db)):
    doc = _doc_or_404(db, document_id)
    if doc.status not in ("done", "done_with_errors", "stopped"):
        raise HTTPException(409, "the document is still being read")
    if not body.language.strip():
        raise HTTPException(400, "language is empty")
    job = enqueue(db, "translate", {"language": body.language.strip()}, doc.id)
    db.commit()
    return {"job_id": str(job.id)}


@app.get(f"{API}/documents/{{document_id}}/export")
def download(document_id: uuid.UUID, format: str = "docx", db: Session = Depends(get_db)):
    if format not in FORMATS:
        raise HTTPException(400, f"format must be one of {sorted(FORMATS)}")
    doc = _doc_or_404(db, document_id)
    ir = build_ir(db, doc)
    stem = Path(doc.filename).stem
    if format == "docx":
        data = export.to_docx(ir)
    elif format == "pdf":
        data = export.to_searchable_pdf(ir)
    elif format == "txt":
        data = export.to_txt(ir).encode()
    elif format == "md":
        data = export.to_md(ir).encode()
    elif format == "json":
        data = export.to_json(ir).encode()
    elif format == "bibtex":
        data = export.to_bibtex(doc.filename, doc.title, doc.created_at).encode()
    else:
        pages = db.scalars(select(Page).where(Page.document_id == doc.id).order_by(Page.number)).all()
        regions = db.scalars(select(Region).where(Region.document_id == doc.id)).all()
        by_page: dict = {}
        for region in regions:
            by_page.setdefault(region.page_id, []).append(region)
        tei_pages = []
        for page in pages:
            if page.status not in ("done", "failed"):
                continue
            regs = sorted(by_page.get(page.id, []), key=lambda region: region.idx)
            tei_pages.append({
                "number": page.number,
                "translation": page.translation,
                "translation_language": page.translation_language,
                "regions": [
                    {"type": region.type, "text": region.text, "x": region.x, "y": region.y,
                     "w": region.w, "h": region.h}
                    for region in regs
                ],
            })
        data = export.to_tei(doc.filename, doc.title or doc.filename, tei_pages)
    ext = "bib" if format == "bibtex" else format
    return Response(data, media_type=FORMATS[format], headers={
        "Content-Disposition": f'attachment; filename="{stem}.{ext}"'
    })


@app.get(f"{API}/search")
def search(
    q: str,
    document_id: uuid.UUID | None = None,
    collection: str | None = None,
    language: str | None = None,
    engine: str | None = None,
    uploaded_from: date | None = None,
    uploaded_to: date | None = None,
    db: Session = Depends(get_db),
):
    return workspace_search(
        db, q, document_id, collection, language, engine, uploaded_from, uploaded_to,
    )


@app.get(f"{API}/library/search")
def library_search(q: str, sources: str = "", db: Session = Depends(get_db)):
    if not q.strip():
        raise HTTPException(400, "query is empty")
    chosen = [part.strip() for part in sources.split(",") if part.strip()] or list(DEFAULT_SOURCES)
    results = search_libraries(db, q.strip(), chosen, limit=8)
    return {"query": q.strip(), "sources": [result.to_json() for result in results]}


@app.get(f"{API}/jobs/{{job_id}}")
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return {
        "id": str(job.id),
        "kind": job.kind,
        "document_id": str(job.document_id) if job.document_id else None,
        "status": job.status,
        "error": job.error,
        "result": job.result,
        "attempts": job.attempts,
    }


class SettingsIn(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    ocr_engine: str | None = None


class AccessIn(BaseModel):
    kind: str
    value: str
    is_admin: bool = False


class DocPatch(BaseModel):
    title: str | None = None
    collection: str | None = None
    language: str | None = None


def _settings_view(db: Session, user: dict | None) -> dict:
    runtime = load_runtime(db)
    saved = db.get(AppSetting, "llm_api_key")
    saved_key = (saved.value if saved else "") or ""
    return {
        "provider": runtime.provider,
        "model": runtime.model,
        "api_base": runtime.api_base,
        "key_set": runtime.configured,
        "key_mask": mask_secret(saved_key) if runtime.key_source == "saved" else "",
        "key_source": runtime.key_source,
        "ocr_engine": runtime.ocr_engine,
        "engines": [
            {"id": "tesseract", "needs_key": False},
            {"id": "ppocr", "needs_key": False},
            {"id": "claude", "needs_key": True},
            {"id": "gemini", "needs_key": True},
        ],
        "llm": runtime.configured,
        "is_admin": bool(user and user.get("is_admin")),
        "auth_disabled": settings.auth_disabled,
    }


@app.get(f"{API}/auth/login")
def auth_login():
    base = settings.app_base_url.rstrip("/")
    if settings.auth_disabled:
        return RedirectResponse(base + "/")
    if not settings.google_client_id or not settings.google_client_secret:
        return RedirectResponse(base + "/login?error=config")
    url, state = auth.login_redirect()
    response = RedirectResponse(url)
    response.set_cookie(
        auth.STATE_COOKIE,
        auth.sign_state(state),
        httponly=True,
        samesite="lax",
        secure=auth.cookie_secure(),
        max_age=600,
        path="/",
    )
    return response


@app.get(f"{API}/auth/callback")
def auth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    from urllib.parse import quote

    base = settings.app_base_url.rstrip("/")
    if error or not code:
        return RedirectResponse(f"{base}/access-denied?reason=cancelled")
    if not auth.state_matches(request.cookies.get(auth.STATE_COOKIE), state):
        return RedirectResponse(f"{base}/access-denied?reason=state")
    try:
        profile = auth.exchange_code(code)
    except Exception:
        log.exception("Google sign-in failed")
        return RedirectResponse(f"{base}/access-denied?reason=google")
    allowed, is_admin = auth.email_allowed(db, profile["email"])
    target = f"{base}/" if allowed else f"{base}/access-denied?email={quote(profile['email'])}"
    response = RedirectResponse(target)
    response.delete_cookie(auth.STATE_COOKIE, path="/")
    if not allowed:
        return response
    auth.set_session_cookie(response, auth.open_session(db, profile["email"], is_admin))
    return response


@app.post(f"{API}/auth/logout")
def auth_logout(request: Request, db: Session = Depends(get_db)):
    auth.drop_session(db, request.cookies.get(auth.COOKIE))
    response = Response(content='{"ok":true}', media_type="application/json")
    auth.clear_session_cookie(response)
    return response


@app.get(f"{API}/auth/me")
def auth_me(request: Request, db: Session = Depends(get_db)):
    user = auth.read_user(request, db)
    if user is None:
        return {"authenticated": False, "auth_disabled": False, "email": None, "is_admin": False}
    return user


@app.get(f"{API}/settings")
def get_settings(user: dict = Depends(require_user), db: Session = Depends(get_db)):
    return _settings_view(db, user)


@app.put(f"{API}/settings")
def save_settings(body: SettingsIn, user: dict = Depends(require_user), db: Session = Depends(get_db)):
    auth.require_admin(user)
    if body.provider is not None:
        put_setting(db, "llm_provider", body.provider.strip()[:40])
    if body.model is not None:
        put_setting(db, "llm_model", body.model.strip()[:200])
    if body.api_base is not None:
        put_setting(db, "llm_api_base", body.api_base.strip()[:300])
    if body.api_key and body.api_key.strip():
        put_setting(db, "llm_api_key", body.api_key.strip())
    if body.ocr_engine:
        if body.ocr_engine not in ENGINES:
            raise HTTPException(400, "Unknown OCR engine.")
        put_setting(db, "ocr_engine", body.ocr_engine)
    db.commit()
    return _settings_view(db, user)


@app.delete(f"{API}/settings/key")
def clear_settings_key(user: dict = Depends(require_user), db: Session = Depends(get_db)):
    auth.require_admin(user)
    row = db.get(AppSetting, "llm_api_key")
    if row is not None:
        db.delete(row)
        db.commit()
    return _settings_view(db, user)


@app.post(f"{API}/settings/test")
def test_settings(body: SettingsIn, user: dict = Depends(require_user), db: Session = Depends(get_db)):
    from .llm import complete
    from .runtime import Runtime

    auth.require_admin(user)
    runtime = load_runtime(db)
    key = (body.api_key or "").strip() or runtime.api_key
    model = (body.model or "").strip() or runtime.model
    base = body.api_base if body.api_base is not None else runtime.api_base
    if not key:
        raise HTTPException(400, "Paste a key, or save one, before testing.")
    trial = Runtime(key, model, base or "", body.provider or runtime.provider, runtime.ocr_engine, "saved")
    try:
        with use_runtime(trial):
            reply = complete("Reply with the single word pong.", "ping")
    except Exception as exc:
        message = str(exc).replace(key, "••••")[:300] or "The key was rejected."
        return {"ok": False, "detail": message}
    return {"ok": True, "detail": (reply or "pong").strip()[:80]}


@app.get(f"{API}/access")
def list_access(user: dict = Depends(require_user), db: Session = Depends(get_db)):
    auth.require_admin(user)
    rows = db.scalars(select(AccessEntry).order_by(AccessEntry.kind, AccessEntry.value)).all()
    return [
        {"id": str(row.id), "kind": row.kind, "value": row.value, "is_admin": row.is_admin, "source": row.source}
        for row in rows
    ]


@app.post(f"{API}/access")
def add_access(body: AccessIn, user: dict = Depends(require_user), db: Session = Depends(get_db)):
    auth.require_admin(user)
    if body.kind not in ("email", "domain"):
        raise HTTPException(400, "Kind must be email or domain.")
    value = body.value.strip().lower().lstrip("@")
    if body.kind == "email" and "@" not in value:
        raise HTTPException(400, "That does not look like an email address.")
    if not value:
        raise HTTPException(400, "Enter an email or a domain.")
    existing = db.scalar(select(AccessEntry).where(AccessEntry.kind == body.kind, AccessEntry.value == value))
    if existing is None:
        db.add(AccessEntry(kind=body.kind, value=value, is_admin=body.is_admin, source="local"))
    elif body.is_admin:
        existing.is_admin = True
    db.commit()
    return list_access(user, db)


@app.delete(f"{API}/access/{{entry_id}}")
def remove_access(entry_id: uuid.UUID, user: dict = Depends(require_user), db: Session = Depends(get_db)):
    auth.require_admin(user)
    row = db.get(AccessEntry, entry_id)
    if row is None:
        raise HTTPException(404, "That entry is not on the list.")
    if row.is_admin and auth.admin_count(db) <= 1:
        raise HTTPException(400, "The last admin cannot be removed.")
    db.delete(row)
    db.commit()
    return {"deleted": str(entry_id)}


@app.get(f"{API}/ocr/models")
def ocr_models():
    return model_status()


@app.patch(f"{API}/documents/{{document_id}}")
def patch_document(document_id: uuid.UUID, body: DocPatch, db: Session = Depends(get_db)):
    doc = _doc_or_404(db, document_id)
    if body.title is not None:
        doc.title = body.title.strip()[:500] or doc.filename
    if body.collection is not None:
        doc.collection = body.collection.strip()[:200] or None
    if body.language is not None:
        doc.language = body.language.strip()[:40] or None
    db.commit()
    return _document_json(db, doc)
