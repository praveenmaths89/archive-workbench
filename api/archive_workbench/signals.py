"""Image-quality signals and the complexity router for vision OCR."""
from __future__ import annotations

import cv2
import numpy as np

from .config import settings
from .ir import Routing


def image_signals(img_bgr: np.ndarray) -> dict:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    scale = 1200 / max(h, w)
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    contrast = float(gray.std())
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink = float(bw.mean() / 255.0)
    bg = cv2.GaussianBlur(gray, (0, 0), 25)
    unevenness = float(bg.std())
    return {
        "blur": round(blur, 1),
        "contrast": round(contrast, 1),
        "ink_density": round(ink, 3),
        "bg_unevenness": round(unevenness, 1),
    }


def is_blank(signals: dict) -> bool:
    return signals["ink_density"] < 0.002 and signals["contrast"] < 8


def route(signals: dict, text_layer_chars: int) -> Routing:
    """Pick a tier from signals. Score is 0 (easy) .. 1 (hard)."""
    reasons: list[str] = []
    if text_layer_chars >= 200:
        return Routing(tier=1, score=0.0, model="text_layer",
                       reasons=[f"born-digital text layer ({text_layer_chars} chars)"])

    score = 0.35
    reasons.append("no usable text layer (scan)")
    if signals["blur"] < 60:
        score += 0.2
        reasons.append(f"low sharpness ({signals['blur']})")
    if signals["contrast"] < 45:
        score += 0.15
        reasons.append(f"low contrast ({signals['contrast']})")
    if signals["bg_unevenness"] > 25:
        score += 0.15
        reasons.append(f"uneven background / staining ({signals['bg_unevenness']})")
    if signals["ink_density"] > 0.25:
        score += 0.1
        reasons.append(f"very dense dark areas ({signals['ink_density']})")
    score = min(score, 1.0)

    if settings.historical_bias:
        tier = 3
        reasons.append("historical-corpus bias: scans go to the strongest tier")
    else:
        tier = 1 if score < 0.35 else 2 if score < 0.6 else 3
    return Routing(tier=tier, score=round(score, 2), model=settings.model_for_tier(tier), reasons=reasons)


def next_tier(r: Routing) -> Routing | None:
    if r.tier >= 3:
        return None
    t = r.tier + 1
    return Routing(tier=t, score=r.score, model=settings.model_for_tier(t),
                   reasons=r.reasons + [f"escalated from tier {r.tier}"], escalated_from=r.tier)
