"""Tesseract by default. Claude or Gemini vision when a key is set.

The vision prompt is the v0.2 transcription prompt, plus a request for a box on each block.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import numpy as np
from PIL import Image

from .config import settings
from .ingest import to_jpeg
from .ir import Routing
from .signals import image_signals, next_tier, route

log = logging.getLogger("ocr")

OCR_PROMPT = """You are transcribing a page from a historical document (possibly handwritten, \
degraded, or in an old typeface). Transcribe EXACTLY what is written, preserving original spelling, \
punctuation, abbreviations and capitalisation. Do not modernise, correct or translate.
Mark unreadable words as [illegible] and uncertain readings as [word?].

Layout rules:
- Each distinct text element is its own block: a printed form label, a handwritten entry, a stamp, a \
margin note, an address, a paragraph. Never merge a printed label into a handwritten line.
- Keep reading order; for two columns, finish one column before the next.
- Tables: use type "table" and give the cells in "rows" (list of rows, each a list of cell strings, \
empty string for empty cells). Do not use pipe characters.
- Charts, maps and diagrams: type "figure". Give title, captions, legends and labels ONCE; describe axis \
scales in a single short line (e.g. "Both vertical axes: 10,000-200,000 acres/rupees") instead of listing \
every tick or repeating the same labels. Transcribe all running text and numeric tables in full.
- Omit scanner or digitisation footers/watermarks (e.g. "Scanned by Camera Scanner") and page-edge artefacts.
- Marginalia, stamps, folio numbers and annotations: type "marginalia".
- Include "bbox" on every block: [x, y, w, h] as fractions of page width and height, between 0 and 1, \
origin at the top left. Give your best estimate when the edges are unclear.

Return ONLY a JSON object, no prose:
{"language": "<ISO 639-1 code of the main language or 'unknown'>",
 "confidence": <0..1 overall confidence in the transcription>,
 "blocks": [{"type": "heading|paragraph|list_item|table|figure|marginalia|other",
             "text": "<transcribed text; empty for tables>", "rows": [["cell"]],
             "bbox": [x, y, w, h], "confidence": <0..1>}]}
Omit "rows" for non-table blocks. If the page is blank, return an empty blocks list."""

UNCERTAIN = re.compile(r"\[illegible\]|\[[^\[\]]{1,40}\?\]")


def is_digitisation_watermark(text: str) -> bool:
    """Drop the 'Scanned by Camera Scanner' footer the v0.2 prompt told the model to ignore."""
    return "camera scanner" in text.lower() and len(text) < 80


class FatalProviderError(RuntimeError):
    """A failure that will hit every later page (bad key, no credit)."""


def fatal_message(exc: Exception) -> str | None:
    text = str(exc).lower()
    if "credit balance" in text or "insufficient_quota" in text or "billing" in text:
        return ("The model provider refused the call because the account has no credit. "
                "Finished pages are kept.")
    name = type(exc).__name__
    if name in ("AuthenticationError", "PermissionDeniedError") or "invalid x-api-key" in text or "api key" in text:
        return "The model API key was rejected. Check LLM_API_KEY in the .env file."
    return None


def count_uncertain(text: str) -> int:
    return len(UNCERTAIN.findall(text))


def needs_review(uncertain: int, confidence: float) -> bool:
    return uncertain >= 3 or (0 < confidence < 0.6)


def parse_ocr_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    return json.loads(text)


def ocr_tesseract(image: Image.Image, langs: str | None = None) -> list[dict]:
    import pytesseract

    langs = langs or settings.tesseract_langs
    try:
        data = pytesseract.image_to_data(image, lang=langs, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError:
        log.warning("Tesseract languages %s failed; falling back to eng", langs)
        data = pytesseract.image_to_data(image, lang="eng", output_type=pytesseract.Output.DICT)
    groups: dict[tuple, dict] = {}
    n = len(data["text"])
    for i in range(n):
        word = (data["text"][i] or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if conf < 0 or not word:
            continue
        x, y, w, h = int(data["left"][i]), int(data["top"][i]), int(data["width"][i]), int(data["height"][i])
        # Tesseract sometimes emits one glyph with a box as tall as the page.
        if h > image.height * 0.2 or w > image.width * 0.95:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        box = groups.setdefault(key, {"words": [], "conf": [], "x0": 10**9, "y0": 10**9, "x1": 0, "y1": 0})
        box["words"].append(word)
        box["conf"].append(conf)
        box["x0"] = min(box["x0"], x)
        box["y0"] = min(box["y0"], y)
        box["x1"] = max(box["x1"], x + w)
        box["y1"] = max(box["y1"], y + h)
    regions = []
    for key in sorted(groups):
        box = groups[key]
        text = " ".join(box["words"])
        if is_digitisation_watermark(text):
            continue
        regions.append({
            "type": "line",
            "text": text,
            "x": box["x0"],
            "y": box["y0"],
            "w": max(1, box["x1"] - box["x0"]),
            "h": max(1, box["y1"] - box["y0"]),
            "confidence": (sum(box["conf"]) / len(box["conf"])) / 100.0,
            "rows": None,
        })
    return regions


def _box_from_fraction(bbox: Any, width: int, height: int, index: int, count: int) -> tuple[int, int, int, int]:
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            x, y, w, h = (float(v) for v in bbox)
            return (
                max(0, int(x * width)),
                max(0, int(y * height)),
                max(1, int(w * width)),
                max(1, int(h * height)),
            )
        except (TypeError, ValueError):
            pass
    band = height / max(count, 1)
    return (int(0.06 * width), int(index * band), int(0.88 * width), max(1, int(band * 0.75)))


def regions_from_vision_json(data: dict, width: int, height: int) -> tuple[list[dict], str | None, float]:
    blocks = data.get("blocks") or []
    regions = []
    for i, block in enumerate(blocks):
        rows = block.get("rows")
        if rows:
            rows = [[str(c) for c in row] for row in rows if isinstance(row, list)]
        text = str(block.get("text") or "")
        if rows and not text.strip():
            text = "\n".join("\t".join(row) for row in rows)
        if not text.strip() and not rows:
            continue
        x, y, w, h = _box_from_fraction(block.get("bbox"), width, height, i, len(blocks))
        regions.append({
            "type": str(block.get("type") or "paragraph"),
            "text": text,
            "x": x, "y": y, "w": w, "h": h,
            "confidence": float(block.get("confidence") or data.get("confidence") or 0),
            "rows": rows,
        })
    return regions, data.get("language"), float(data.get("confidence") or 0)


def ocr_vision(img_bgr: np.ndarray, model: str) -> tuple[list[dict], str | None, float, Routing]:
    from .llm import complete_vision

    signals = image_signals(img_bgr)
    routing = route(signals, 0)
    routing.model = model or routing.model
    height, width = img_bgr.shape[:2]
    jpeg = to_jpeg(img_bgr, max_edge=settings.api_image_max_edge)
    tried: list[str] = []
    while True:
        if routing.model in tried:
            break
        tried.append(routing.model)
        try:
            raw = complete_vision(OCR_PROMPT, jpeg, model=routing.model)
        except Exception as exc:
            fatal = fatal_message(exc)
            if fatal:
                raise FatalProviderError(fatal) from exc
            raise
        try:
            data = parse_ocr_json(raw)
        except (json.JSONDecodeError, ValueError):
            data = {"language": None, "confidence": 0.3,
                    "blocks": [{"type": "paragraph", "text": raw, "confidence": 0.3}]}
        regions, language, confidence = regions_from_vision_json(data, width, height)
        if confidence >= settings.escalation_threshold:
            break
        nxt = next_tier(routing)
        if nxt is None or nxt.model == routing.model:
            break
        routing = nxt
    return regions, language, confidence, routing
