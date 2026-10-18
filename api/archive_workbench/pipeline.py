"""OCR, embed, explain, and translate jobs."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

import cv2
import pymupdf
from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .embeddings import get_embedder
from .ingest import get_page, to_jpeg
from .ir import Block, DocumentIR, Page as IRPage
from .llm import complete, configured
from .models import Chunk, Document, Page, Region
from .ocr import (
    FatalProviderError,
    count_uncertain,
    needs_review,
    ocr_tesseract,
    ocr_vision,
)
from .queue import enqueue
from .signals import image_signals, is_blank

log = logging.getLogger("pipeline")

EXPLAIN_SYSTEM = (
    "You write a two or three sentence explanation of a historical document for a researcher. "
    "Use only the transcription. Quote a short phrase from it. Do not invent events or context."
)
TRANSLATE_SYSTEM = (
    "You translate historical transcriptions. Keep proper names, dates, and [illegible] or [word?] "
    "markers as they are. Do not add commentary. Return only the translation."
)


def document_dir(document_id: uuid.UUID) -> Path:
    path = settings.data_dir / "documents" / str(document_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def page_image_path(document_id: uuid.UUID, number: int) -> Path:
    return document_dir(document_id) / f"page_{number:04d}.jpg"


def text_layer_regions(path: Path, number: int, width: int, height: int) -> list[dict]:
    with pymupdf.open(path) as doc:
        page = doc[number - 1]
        pw, ph = page.rect.width or 1, page.rect.height or 1
        sx, sy = width / pw, height / ph
        regions = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = "".join(span["text"] for span in line["spans"]).strip()
                if not text:
                    continue
                x0, y0, x1, y1 = line["bbox"]
                regions.append({
                    "type": "line",
                    "text": text,
                    "x": int(x0 * sx),
                    "y": int(y0 * sy),
                    "w": max(1, int((x1 - x0) * sx)),
                    "h": max(1, int((y1 - y0) * sy)),
                    "confidence": 1.0,
                    "rows": None,
                })
        return regions


def _replace_regions(session: Session, page: Page, regions: list[dict]) -> None:
    session.execute(delete(Region).where(Region.page_id == page.id))
    session.flush()
    for index, region in enumerate(regions):
        session.add(Region(
            document_id=page.document_id,
            page_id=page.id,
            idx=index,
            type=region.get("type") or "line",
            text=region.get("text") or "",
            x=int(region.get("x") or 0),
            y=int(region.get("y") or 0),
            w=int(region.get("w") or 0),
            h=int(region.get("h") or 0),
            confidence=float(region.get("confidence") or 0),
        ))


def _apply_text(page: Page, regions: list[dict], engine: str, language: str | None = None) -> None:
    text = "\n".join(region["text"] for region in regions if region.get("text"))
    confs = [float(region.get("confidence") or 0) for region in regions]
    page.text = text
    page.ocr_engine = engine
    page.language = language
    page.confidence = sum(confs) / len(confs) if confs else (1.0 if engine in ("blank", "text_layer") else 0.0)
    page.uncertain = count_uncertain(text)
    page.flagged = needs_review(page.uncertain, page.confidence)
    page.status = "done"
    page.error = None


def _is_scan(src: Path, kind: str, number: int) -> bool:
    """A page that is itself an image, or a PDF page that embeds one (a scan)."""
    if kind != "pdf":
        return True
    with pymupdf.open(src) as doc:
        return bool(doc[number - 1].get_images())


def read_page(src: Path, kind: str, number: int, engine: str, force_ocr: bool) -> tuple[list[dict], str, str | None]:
    img, text_layer = get_page(src, kind, number)
    height, width = img.shape[:2]
    signals = image_signals(img)
    if is_blank(signals) and len(text_layer) < 20:
        return [], "blank", None
    # Born-digital pages keep their text layer. Scans are read with the OCR engine
    # even when a previous text layer is present, so the boxes match the image.
    if (not force_ocr and engine == "tesseract" and len(text_layer) >= 200
            and not _is_scan(src, kind, number)):
        regions = text_layer_regions(src, number, width, height) if kind == "pdf" else []
        if not regions:
            regions = [{"type": "paragraph", "text": text_layer, "x": 0, "y": 0,
                        "w": width, "h": height, "confidence": 1.0, "rows": None}]
        return regions, "text_layer", None
    if engine == "tesseract":
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        return ocr_tesseract(pil), "tesseract", None
    model = settings.model_for_tier(3) if engine == "claude" else settings.llm_model
    if engine == "gemini" and not settings.llm_model.startswith("gemini/"):
        model = "gemini/gemini-2.0-flash"
    regions, language, _confidence, _routing = ocr_vision(img, model)
    return regions, engine, language


def run_ocr(session: Session, document_id: uuid.UUID, payload: dict) -> dict:
    doc = session.get(Document, document_id)
    if doc is None:
        raise RuntimeError("document missing")
    doc.status = "processing"
    doc.error = None
    session.commit()

    src = Path(doc.source_path)
    requested = (payload or {}).get("ocr_engine") or settings.ocr_engine
    force_ocr = bool((payload or {}).get("force_ocr"))
    redo = bool((payload or {}).get("redo"))
    page_spec = (payload or {}).get("pages")
    actual = requested
    note = None
    if requested in ("claude", "gemini") and not settings.model_key:
        actual = "tesseract"
        note = "no API key; used Tesseract"

    pages = {p.number: p for p in session.scalars(select(Page).where(Page.document_id == doc.id))}
    for number in range(1, doc.page_count + 1):
        if number not in pages:
            page = Page(document_id=doc.id, number=number, status="skipped")
            session.add(page)
            pages[number] = page
    session.flush()

    wanted = set(page_spec) if page_spec else set(range(1, doc.page_count + 1))
    todo = []
    for number in sorted(wanted):
        page = pages.get(number)
        if page is None:
            continue
        if redo or page.status != "done":
            page.status = "pending"
            todo.append(number)
    session.commit()

    failed = 0
    fatal = None
    for number in todo:
        session.refresh(doc)
        if doc.stop_requested:
            break
        page = pages[number]
        try:
            img, _text = get_page(src, doc.kind, number)
            # Save the JPEG the viewer will use, then OCR that same bitmap via read_page's render.
            # read_page renders again; dimensions match because both use render_dpi.
            image_path = page_image_path(doc.id, number)
            image_path.write_bytes(to_jpeg(img))
            page.image_path = str(image_path)
            page.width = int(img.shape[1])
            page.height = int(img.shape[0])
            regions, engine, language = read_page(src, doc.kind, number, actual, force_ocr)
            _replace_regions(session, page, regions)
            _apply_text(page, regions, engine, language)
            if language and not doc.language:
                doc.language = language
        except FatalProviderError as exc:
            fatal = str(exc)
            page.status = "failed"
            page.error = fatal
            failed += 1
            doc.error = fatal
            break
        except Exception as exc:
            log.exception("page %s failed", number)
            page.status = "failed"
            page.error = f"{type(exc).__name__}: {exc}"
            failed += 1
        session.commit()

    for page in pages.values():
        if page.status == "pending":
            page.status = "skipped"
    if fatal:
        doc.status = "failed"
        doc.error = fatal
    elif doc.stop_requested:
        doc.status = "stopped"
    session.commit()
    return {"requested_engine": requested, "engine": actual, "note": note, "failed_pages": failed, "fatal": fatal}


def run_embed(session: Session, document_id: uuid.UUID) -> dict:
    session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    session.flush()
    pages = {p.id: p for p in session.scalars(select(Page).where(Page.document_id == document_id))}
    regions = session.scalars(select(Region).where(Region.document_id == document_id)).all()
    by_page: dict = {}
    for region in regions:
        by_page.setdefault(region.page_id, []).append(region)
    groups: list[list[Region]] = []
    for page_id, regs in by_page.items():
        regs.sort(key=lambda region: region.idx)
        buf: list[Region] = []
        size = 0
        for region in regs:
            if buf and size + len(region.text) > 500:
                groups.append(buf)
                buf = []
                size = 0
            if not region.text.strip():
                continue
            buf.append(region)
            size += len(region.text) + 1
        if buf:
            groups.append(buf)
    texts = ["\n".join(region.text for region in group) for group in groups]
    vectors = get_embedder().embed_passages(texts) if texts else []
    for group, text, vector in zip(groups, texts, vectors):
        page = pages[group[0].page_id]
        session.add(Chunk(
            document_id=document_id,
            page_id=page.id,
            region_id=group[0].id,
            page_number=page.number,
            text=text,
            embedding=vector,
        ))
    doc = session.get(Document, document_id)
    if doc is not None:
        _settle(doc, list(pages.values()))
    session.commit()
    return {"chunks": len(groups)}


def _settle(doc: Document, pages: list[Page]) -> None:
    if doc.status == "failed" and doc.error:
        return
    if doc.stop_requested:
        doc.status = "stopped"
        return
    chosen = [p for p in pages if p.status != "skipped"]
    failed = [p for p in chosen if p.status == "failed"]
    if chosen and len(failed) == len(chosen):
        doc.status = "failed"
        doc.error = doc.error or failed[0].error
    elif failed:
        doc.status = "done_with_errors"
    else:
        doc.status = "done"


def run_explain(session: Session, document_id: uuid.UUID) -> dict:
    doc = session.get(Document, document_id)
    if doc is None:
        return {}
    pages = session.scalars(
        select(Page).where(Page.document_id == document_id).order_by(Page.number)
    ).all()
    sample = "\n".join(p.text for p in pages if p.text).strip()
    if not sample:
        doc.explanation = "No transcription was produced for this document."
    elif configured():
        doc.explanation = complete(EXPLAIN_SYSTEM, f"Filename: {doc.filename}\n\n{sample[:4000]}")
    else:
        snippet = " ".join(sample.split())[:400]
        doc.explanation = (
            f"{doc.filename} has {doc.page_count} page(s). The transcription begins: {snippet}"
        )
    session.commit()
    return {"explanation": doc.explanation}


def run_translate(session: Session, document_id: uuid.UUID, language: str) -> dict:
    pages = session.scalars(
        select(Page).where(Page.document_id == document_id).order_by(Page.number)
    ).all()
    for page in pages:
        if page.status != "done" or not page.text.strip():
            continue
        if configured():
            page.translation = complete(
                TRANSLATE_SYSTEM,
                f"Translate into {language}:\n\n{page.text[:8000]}",
            )
        else:
            page.translation = f"[mock translation to {language}]\n{page.text}"
        page.translation_language = language
    session.commit()
    return {"language": language, "mock": not configured()}


def build_ir(session: Session, doc: Document) -> DocumentIR:
    pages = session.scalars(select(Page).where(Page.document_id == doc.id).order_by(Page.number)).all()
    regions = session.scalars(select(Region).where(Region.document_id == doc.id)).all()
    by_page: dict = {}
    for region in regions:
        by_page.setdefault(region.page_id, []).append(region)
    ir_pages = []
    for page in pages:
        regs = sorted(by_page.get(page.id, []), key=lambda region: region.idx)
        blocks = [Block(type=region.type if region.type != "line" else "paragraph",
                        text=region.text, confidence=region.confidence) for region in regs]
        if page.translation:
            blocks.append(Block(type="heading", text=f"Translation ({page.translation_language or ''})".strip()))
            blocks.append(Block(type="paragraph", text=page.translation))
        ir_pages.append(IRPage(
            number=page.number,
            image_path=page.image_path,
            source=page.ocr_engine or "ocr",
            language=page.language,
            confidence=page.confidence,
            blocks=blocks,
            status=page.status if page.status in ("done", "failed") else "skipped",
            error=page.error,
            flagged=page.flagged,
            uncertain=page.uncertain,
            edited=page.edited,
        ))
    return DocumentIR(doc_id=str(doc.id), filename=doc.filename, pages=ir_pages)


def queue_followups(session: Session, document_id: uuid.UUID) -> None:
    enqueue(session, "embed", {}, document_id)
    enqueue(session, "explain", {}, document_id)
    session.commit()
