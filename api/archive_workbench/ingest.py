"""File validation and page rendering. Adapted from the v0.2 prototype."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageSequence

from .config import settings

MAGIC = [
    (b"%PDF", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "image"),
    (b"\xff\xd8\xff", "image"),
    (b"II*\x00", "image"),
    (b"MM\x00*", "image"),
]


class IngestError(ValueError):
    pass


def detect_kind(path: Path) -> str:
    head = path.read_bytes()[:16] if path.stat().st_size else b""
    for sig, kind in MAGIC:
        if head.startswith(sig):
            return kind
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image"
    raise IngestError("unsupported or corrupt file type")


def page_count(path: Path, kind: str) -> int:
    if kind == "pdf":
        with pymupdf.open(path) as doc:
            if doc.needs_pass:
                raise IngestError("PDF is password-protected")
            return doc.page_count
    with Image.open(path) as im:
        return getattr(im, "n_frames", 1)


def _pix_to_bgr(pix: "pymupdf.Pixmap") -> np.ndarray:
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
    if pix.n == 1:
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def iter_pages(path: Path, kind: str, only: set[int] | None = None) -> Iterator[tuple[int, np.ndarray, str]]:
    if kind == "pdf":
        with pymupdf.open(path) as doc:
            zoom = settings.render_dpi / 72
            for i in sorted(only) if only else range(1, doc.page_count + 1):
                page = doc[i - 1]
                text = page.get_text("text").strip()
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                yield i, _pix_to_bgr(pix), text
    else:
        with Image.open(path) as im:
            for i, frame in enumerate(ImageSequence.Iterator(im), start=1):
                if only and i not in only:
                    continue
                rgb = np.array(frame.convert("RGB"))
                yield i, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), ""


def to_jpeg(img_bgr: np.ndarray, max_edge: int | None = None, quality: int = 88) -> bytes:
    h, w = img_bgr.shape[:2]
    if max_edge and max(h, w) > max_edge:
        s = max_edge / max(h, w)
        img_bgr = cv2.resize(img_bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise IngestError("could not encode page image")
    return buf.tobytes()


def get_page(path: Path, kind: str, number: int) -> tuple[np.ndarray, str]:
    """Render a single page (1-based)."""
    if kind == "pdf":
        with pymupdf.open(path) as doc:
            page = doc[number - 1]
            zoom = settings.render_dpi / 72
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            return _pix_to_bgr(pix), page.get_text("text").strip()
    with Image.open(path) as im:
        im.seek(number - 1)
        return cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2BGR), ""
