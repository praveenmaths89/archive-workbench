"""PP-OCRv4 through RapidOCR and ONNX Runtime.

Weights are Apache-2.0 and are downloaded on first use into DATA_DIR.
Tesseract remains the fallback when this cannot run.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
from PIL import Image

from .config import settings

log = logging.getLogger("ppocr")

# RapidOCR redistributes these PP-OCRv4 / multilingual PP-OCRv3 files under Apache-2.0.
BASE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v2.1.0"
FILES = {
    "det.onnx": f"{BASE}/onnx/PP-OCRv4/det/Multilingual_PP-OCRv3_det_infer.onnx",
    "en.onnx": f"{BASE}/onnx/PP-OCRv4/rec/en_PP-OCRv4_rec_infer.onnx",
    "en_dict.txt": f"{BASE}/paddle/PP-OCRv4/rec/en_PP-OCRv4_rec_infer/en_dict.txt",
    "devanagari.onnx": f"{BASE}/onnx/PP-OCRv4/rec/devanagari_PP-OCRv4_rec_infer.onnx",
    "devanagari_dict.txt": f"{BASE}/paddle/PP-OCRv4/rec/devanagari_PP-OCRv4_rec_infer/devanagari_dict.txt",
    "ka.onnx": f"{BASE}/onnx/PP-OCRv4/rec/ka_PP-OCRv4_rec_infer.onnx",
    "ka_dict.txt": f"{BASE}/paddle/PP-OCRv4/rec/kannada_PP-OCRv4_rec_infer/ka_dict.txt",
}
SCRIPTS = (
    ("en", "en.onnx", "en_dict.txt"),
    ("devanagari", "devanagari.onnx", "devanagari_dict.txt"),
    ("kannada", "ka.onnx", "ka_dict.txt"),
)

_engines: dict[str, object] = {}


def model_dir() -> Path:
    path = settings.data_dir / "models" / "ppocr"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _status_path() -> Path:
    return model_dir() / "status.json"


def write_status(state: str, message: str, done: int = 0, total: int = len(FILES)) -> None:
    _status_path().write_text(json.dumps({
        "state": state,
        "message": message,
        "done": done,
        "total": total,
    }))


def model_status() -> dict:
    path = _status_path()
    ready = all((model_dir() / name).exists() and (model_dir() / name).stat().st_size > 0 for name in FILES)
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}
    if ready:
        data["state"] = "ready"
        data.setdefault("message", "PP-OCR models are ready.")
    else:
        data.setdefault("state", "missing")
        data.setdefault("message", "PP-OCR models download on the first page that uses them.")
    data["ready"] = ready
    return data


def _download(url: str, dest: Path, label: str) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
    tmp.replace(dest)
    log.info("downloaded %s (%s bytes)", label, dest.stat().st_size)


def ensure_models(on_progress=None) -> Path:
    folder = model_dir()
    missing = [name for name in FILES if not (folder / name).exists() or (folder / name).stat().st_size == 0]
    if not missing:
        write_status("ready", "PP-OCR models are ready.", len(FILES), len(FILES))
        return folder
    total = len(FILES)
    done = total - len(missing)
    for name in missing:
        done += 1
        message = f"Downloading {name} ({done} of {total})"
        write_status("downloading", message, done, total)
        if on_progress:
            on_progress(message)
        try:
            _download(FILES[name], folder / name, name)
        except Exception as exc:
            write_status("error", f"Could not download {name}: {exc}", done, total)
            raise
    write_status("ready", "PP-OCR models are ready.", total, total)
    if on_progress:
        on_progress("Reading the page with PP-OCR…")
    return folder


def quad_to_box(points) -> tuple[int, int, int, int]:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    return int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0))


def _iou(a: dict, b: dict) -> float:
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    ix0, iy0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    ix1, iy1 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    if inter <= 0:
        return 0.0
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union else 0.0


def merge_regions(regions: list[dict]) -> list[dict]:
    """Keep the higher-confidence reading when two script models hit the same line."""
    kept: list[dict] = []
    for region in sorted(regions, key=lambda item: float(item.get("confidence") or 0), reverse=True):
        if not (region.get("text") or "").strip():
            continue
        if any(_iou(region, earlier) > 0.45 for earlier in kept):
            continue
        kept.append(region)
    kept.sort(key=lambda item: (item["y"], item["x"]))
    return kept


def _engine(folder: Path, script: str, onnx_name: str, dict_name: str):
    cached = _engines.get(script)
    if cached is not None:
        return cached
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR(
        det_model_path=str(folder / "det.onnx"),
        rec_model_path=str(folder / onnx_name),
        rec_keys_path=str(folder / dict_name),
        use_cls=False,
        text_score=0.3,
        min_height=8,
    )
    _engines[script] = engine
    return engine


def ocr_ppocr(image: Image.Image, on_progress=None) -> list[dict]:
    folder = ensure_models(on_progress)
    regions: list[dict] = []
    for script, onnx_name, dict_name in SCRIPTS:
        if on_progress:
            on_progress(f"Reading printed text ({script})…")
        engine = _engine(folder, script, onnx_name, dict_name)
        result, _elapsed = engine(image)
        for item in result or []:
            if len(item) < 3:
                continue
            box, text, score = item[0], str(item[1] or ""), float(item[2] or 0)
            x, y, w, h = quad_to_box(box)
            # A box as tall as the page is a detector miss, same rule as Tesseract.
            if h > image.height * 0.2 or w > image.width * 0.95:
                continue
            regions.append({
                "type": "line",
                "text": text.strip(),
                "x": x, "y": y, "w": w, "h": h,
                "confidence": score,
                "rows": None,
            })
    return merge_regions(regions)
