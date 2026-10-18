"""Per-document processing: render -> signals -> route -> OCR -> escalate -> IR."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable, Optional

from .adapters import OcrAdapter
from .config import settings
from .ingest import iter_pages, to_jpeg
from .ir import Block, DocumentIR, Page
from .signals import image_signals, is_blank, next_tier, route

log = logging.getLogger("pipeline")


class FatalProviderError(RuntimeError):
    """An error that will hit every page (billing, bad key, no access): stop the whole run."""


def fatal_message(e: Exception) -> str | None:
    text = str(e).lower()
    if "credit balance is too low" in text:
        return ("Your Anthropic credit balance is too low. Add credits at console.anthropic.com "
                "(Plans & Billing), then press Start again - finished pages are kept.")
    name = type(e).__name__
    if name in ("AuthenticationError", "PermissionDeniedError") or "invalid x-api-key" in text:
        return "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in the .env file."
    return None
UNCERTAIN = re.compile(r"\[illegible\]|\[[^\[\]]{1,40}\?\]")


def count_uncertain(page: Page) -> int:
    return len(UNCERTAIN.findall(page.text))


def needs_review(page: Page) -> bool:
    """Review flag from what the transcription itself marks as doubtful.

    The model's self-reported confidence read 0.78-0.88 on pages that were transcribed well, so it
    only triggers the flag when it is very low."""
    return page.uncertain >= 3 or (0 < page.confidence < 0.6)


def process_page(adapter: OcrAdapter, number: int, img, text_layer: str, out_dir: Path,
                 force_ocr: bool = False, pin_model: Optional[str] = None) -> Page:
    page = Page(number=number)
    img_path = out_dir / f"page_{number:04d}.jpg"
    img_path.write_bytes(to_jpeg(img))
    page.image_path = str(img_path)
    page.signals = image_signals(img)

    if is_blank(page.signals) and len(text_layer) < 20:
        page.status, page.confidence, page.source = "done", 1.0, "blank"
        return page

    layer_chars = 0 if force_ocr else len(text_layer)
    routing = route(page.signals, layer_chars)
    page.routing = routing

    if routing.model == "text_layer":
        page.source = "text_layer"
        paras = [p.strip() for p in text_layer.split("\n\n") if p.strip()] or [text_layer]
        page.blocks = [Block(type="paragraph", text=p, confidence=1.0) for p in paras]
        page.confidence, page.status = 1.0, "done"
        return page

    jpeg = to_jpeg(img, max_edge=settings.api_image_max_edge)
    if pin_model:
        routing.model, routing.reasons = pin_model, routing.reasons + ["model pinned by user"]
    while True:
        try:
            res = adapter.ocr(jpeg, routing.model, {})
        except Exception as e:  # provider error: fail this page, not the document
            fatal = fatal_message(e)
            if fatal:
                raise FatalProviderError(fatal) from e
            log.exception("OCR failed on page %s", number)
            page.status, page.error = "failed", f"{type(e).__name__}: {e}"
            return page
        page.blocks, page.language, page.confidence = res.blocks, res.language, res.confidence
        page.input_tokens += res.input_tokens
        page.output_tokens += res.output_tokens
        page.routing = routing
        if page.confidence >= settings.escalation_threshold or pin_model:
            break
        nxt = next_tier(routing)
        if nxt is None:
            break
        routing = nxt
    page.uncertain = count_uncertain(page)
    page.flagged = needs_review(page)
    page.status = "done"
    return page


def process_document(adapter: OcrAdapter, doc_id: str, filename: str, src: Path, kind: str,
                     out_dir: Path, total_pages: int, pages: list[int] | None = None,
                     on_progress: Callable[[int, int], None] | None = None,
                     force_ocr: bool = False, pin_model: Optional[str] = None,
                     redo: bool = False, should_stop: Callable[[], bool] | None = None) -> DocumentIR:
    """OCR the chosen pages (default all). Pages already done are kept unless `redo`.

    The IR always lists every page of the file; ones not requested stay 'skipped' and can be run later."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ir_path = out_dir / "ir.json"
    ir = DocumentIR.model_validate_json(ir_path.read_text()) if ir_path.exists() \
        else DocumentIR(doc_id=doc_id, filename=filename)
    have = {p.number: p for p in ir.pages}
    ir.pages = [have.get(n) or Page(number=n, status="skipped") for n in range(1, total_pages + 1)]
    wanted = set(pages) if pages else set(range(1, total_pages + 1))
    todo = wanted if redo else {n for n in wanted if ir.pages[n - 1].status not in ("done",)}
    for n in todo:
        if ir.pages[n - 1].status == "skipped":
            ir.pages[n - 1].status = "pending"
    ir_path.write_text(ir.model_dump_json(indent=1))  # viewer can list every page immediately
    def report():
        # progress is over the whole document: pages finished / pages chosen so far (not 'skipped')
        if on_progress:
            chosen = [p for p in ir.pages if p.status != "skipped"]
            on_progress(sum(p.status in ("done", "failed") for p in chosen), len(chosen))

    report()
    try:
        for number, img, text in iter_pages(src, kind, only=todo):
            if should_stop and should_stop():
                break
            ir.pages[number - 1] = process_page(adapter, number, img, text, out_dir, force_ocr, pin_model)
            ir_path.write_text(ir.model_dump_json(indent=1))  # checkpoint after every page
            report()
    finally:
        for p in ir.pages:  # a stop or fatal error leaves queued pages unread: back to 'skipped'
            if p.status == "pending":
                p.status = "skipped"
        ir_path.write_text(ir.model_dump_json(indent=1))
        report()
    return ir
