import io
import time

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import main
from app.adapters import MockAdapter, parse_ocr_json
from app.config import settings
from app.ir import Routing
from app.pipeline import process_page
from app.signals import next_tier, route


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "use_mock", True)


def make_scan_pdf(pages=2) -> bytes:
    """A PDF with image-only pages (no text layer), like a scan."""
    import numpy as np, cv2
    doc = pymupdf.open()
    for i in range(pages):
        img = np.full((800, 600, 3), 235, np.uint8)
        cv2.putText(img, f"page {i}", (50, 400), cv2.FONT_HERSHEY_SIMPLEX, 2, (30, 30, 30), 3)
        ok, jpg = cv2.imencode(".jpg", img)
        p = doc.new_page(width=300, height=400)
        p.insert_image(p.rect, stream=jpg.tobytes())
    return doc.tobytes()


def make_text_pdf() -> bytes:
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_textbox(pymupdf.Rect(50, 50, 500, 700), "Born digital text. " * 40)
    return doc.tobytes()


def test_parse_ocr_json_variants():
    assert parse_ocr_json('```json\n{"blocks": []}\n```') == {"blocks": []}
    assert parse_ocr_json('Here you go: {"blocks": [], "confidence": 0.9} thanks')["confidence"] == 0.9


def test_route_text_layer_is_tier1_no_model():
    r = route({"blur": 100, "contrast": 60, "ink_density": .05, "bg_unevenness": 5}, 500)
    assert r.tier == 1 and r.model == "text_layer"


def test_route_scan_historical_bias_goes_tier3(monkeypatch):
    monkeypatch.setattr(settings, "historical_bias", True)
    r = route({"blur": 100, "contrast": 60, "ink_density": .05, "bg_unevenness": 5}, 0)
    assert r.tier == 3


def test_route_scan_without_bias_scales_with_difficulty(monkeypatch):
    monkeypatch.setattr(settings, "historical_bias", False)
    easy = route({"blur": 100, "contrast": 60, "ink_density": .05, "bg_unevenness": 5}, 0)
    hard = route({"blur": 20, "contrast": 20, "ink_density": .3, "bg_unevenness": 40}, 0)
    assert hard.score > easy.score and hard.tier == 3 and easy.tier == 2


def test_next_tier_chain():
    r = Routing(tier=2, score=.5, model="m2")
    assert next_tier(r).tier == 3 and next_tier(next_tier(r)) is None


def test_escalation_when_low_confidence(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "historical_bias", False)
    import numpy as np
    from app import pipeline
    img = np.random.randint(100, 140, (400, 300, 3), dtype=np.uint8)
    monkeypatch.setattr(pipeline, "route", lambda s, n: Routing(
        tier=2, score=.5, model=settings.model_tier2))
    ad = MockAdapter({settings.model_tier2: 0.5, settings.model_tier3: 0.95})
    page = process_page(ad, 1, img, "", tmp_path)
    assert ad.calls == [settings.model_tier2, settings.model_tier3]
    assert page.routing.tier == 3 and page.routing.escalated_from == 2 and not page.flagged


def test_flagged_when_top_tier_still_low(tmp_path, monkeypatch):
    import numpy as np
    img = np.random.randint(100, 140, (400, 300, 3), dtype=np.uint8)
    ad = MockAdapter({settings.model_tier3: 0.4})
    page = process_page(ad, 1, img, "", tmp_path)
    assert page.flagged and page.status == "done"


def wait_done(client, job_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        docs = client.get(f"/api/v1/jobs/{job_id}").json()["documents"]
        if all(d["status"] not in ("queued", "processing") for d in docs):
            return docs
        time.sleep(0.2)
    raise AssertionError("timeout")


def test_end_to_end_multi_upload_and_exports():
    c = TestClient(main.app)
    files = [("files", ("scan.pdf", make_scan_pdf(2), "application/pdf")),
             ("files", ("born.pdf", make_text_pdf(), "application/pdf")),
             ("files", ("bad.pdf", b"not a pdf at all", "application/pdf"))]
    r = c.post("/api/v1/jobs", files=files)
    assert r.status_code == 200
    job = r.json()["job_id"]
    docs = {d["filename"]: d for d in wait_done(c, job)}
    assert docs["scan.pdf"]["status"] == "done" and docs["scan.pdf"]["total_pages"] == 2
    assert docs["born.pdf"]["status"] == "done"
    assert docs["bad.pdf"]["status"] == "rejected"  # bad file does not fail the batch

    scan_id, born_id = docs["scan.pdf"]["id"], docs["born.pdf"]["id"]
    detail = c.get(f"/api/v1/jobs/{job}/documents/{born_id}").json()
    assert detail["pages"][0]["source"] == "text_layer"
    detail = c.get(f"/api/v1/jobs/{job}/documents/{scan_id}").json()
    assert detail["pages"][0]["routing"]["tier"] == 3

    for fmt, magic in [("docx", b"PK"), ("pdf", b"%PDF"), ("txt", b""), ("md", b""), ("json", b"{")]:
        resp = c.get(f"/api/v1/jobs/{job}/documents/{scan_id}/download?format={fmt}")
        assert resp.status_code == 200 and resp.content.startswith(magic)
    # searchable PDF really carries the text layer
    pdf = pymupdf.open(stream=c.get(f"/api/v1/jobs/{job}/documents/{scan_id}/download?format=pdf").content)
    assert "mock transcription" in pdf[0].get_text()
    z = c.get(f"/api/v1/jobs/{job}/download?format=txt")
    assert z.headers["content-type"] == "application/zip"
    assert c.get(f"/api/v1/jobs/{job}/documents/{scan_id}/download?format=exe").status_code == 400

    rr = c.post(f"/api/v1/jobs/{job}/documents/{scan_id}/pages/1/rerun", json={"model": "claude-sonnet-5-5"})
    assert rr.status_code == 200 and rr.json()["routing"]["model"] == "claude-sonnet-5-5"
    assert c.delete(f"/api/v1/jobs/{job}").status_code == 200


def test_login_enforced(monkeypatch):
    monkeypatch.setattr(main.auth_cfg, "app_password", "secret")
    c = TestClient(main.app)
    assert c.get("/api/v1/models").status_code == 401
    assert c.get("/api/v1/models", auth=("u", "secret")).status_code == 200
