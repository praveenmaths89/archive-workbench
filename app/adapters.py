"""OCR model adapters. Claude is the real one; Mock supports tests and keyless dev."""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol

from .config import settings
from .ir import Block

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

Return ONLY a JSON object, no prose:
{"language": "<ISO 639-1 code of the main language or 'unknown'>",
 "confidence": <0..1 overall confidence in the transcription>,
 "blocks": [{"type": "heading|paragraph|list_item|table|figure|marginalia|other",
             "text": "<transcribed text; empty for tables>", "rows": [["cell"]] , "confidence": <0..1>}]}
Omit "rows" for non-table blocks. If the page is blank, return an empty blocks list."""


@dataclass
class OcrResult:
    blocks: list[Block]
    language: Optional[str] = None
    confidence: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    raw: dict = field(default_factory=dict)


class OcrAdapter(Protocol):
    def ocr(self, jpeg_bytes: bytes, model: str, hints: dict) -> OcrResult: ...


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


def result_from_json(data: dict, in_tok: int, out_tok: int) -> OcrResult:
    blocks = []
    for b in data.get("blocks", []):
        rows = b.get("rows")
        if rows:
            rows = [[str(c) for c in r] for r in rows if isinstance(r, list)]
        text = str(b.get("text", ""))
        if not text.strip() and not rows:
            continue
        blocks.append(Block(type=str(b.get("type", "paragraph")), text=text,
                            confidence=float(b.get("confidence", 0.0)), rows=rows or None))
    return OcrResult(blocks=blocks, language=data.get("language"),
                     confidence=float(data.get("confidence", 0.0)),
                     input_tokens=in_tok, output_tokens=out_tok, raw=data)


class ClaudeAdapter:
    def __init__(self, api_key: str | None = None):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key,
                                          max_retries=4, timeout=300.0)

    def ocr(self, jpeg_bytes: bytes, model: str, hints: dict) -> OcrResult:
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(jpeg_bytes).decode()}},
            {"type": "text", "text": OCR_PROMPT + (f"\nHints: {json.dumps(hints)}" if hints else "")},
        ]
        msg = self.client.messages.create(model=model, max_tokens=8000,
                                          messages=[{"role": "user", "content": content}])
        text = "".join(b.text for b in msg.content if b.type == "text")
        try:
            data = parse_ocr_json(text)
        except (json.JSONDecodeError, ValueError):
            # Model returned prose: keep it as a single low-confidence block rather than lose it.
            data = {"language": None, "confidence": 0.3,
                    "blocks": [{"type": "paragraph", "text": text, "confidence": 0.3}]}
        return result_from_json(data, msg.usage.input_tokens, msg.usage.output_tokens)


class MockAdapter:
    """Deterministic fake. Confidence rises with tier so escalation is testable."""

    def __init__(self, confidence_by_model: dict[str, float] | None = None):
        self.confidence_by_model = confidence_by_model or {}
        self.calls: list[str] = []

    def ocr(self, jpeg_bytes: bytes, model: str, hints: dict) -> OcrResult:
        self.calls.append(model)
        conf = self.confidence_by_model.get(model, 0.95)
        return OcrResult(blocks=[Block(type="paragraph", text=f"[mock transcription by {model}]",
                                       confidence=conf)],
                         language="en", confidence=conf, input_tokens=10, output_tokens=5)


def get_adapter() -> OcrAdapter:
    if settings.use_mock or not settings.anthropic_api_key:
        return MockAdapter()
    return ClaudeAdapter()
