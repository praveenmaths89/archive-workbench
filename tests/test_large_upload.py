"""Large archival PDFs are stored, not rejected at 8 MB, and long files are not sent whole to a model."""
import os

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import main
from app.adapters import MockAdapter
from app.config import settings
from tests.test_pipeline import make_scan_pdf, wait_done


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "hosted_mode", True)
    monkeypatch.setattr(settings, "use_mock", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "cookie_secure", False)


def padded_pdf(min_bytes: int) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 540, 700), "Born digital archive note 1824. " * 20)
    doc.embfile_add("pad.bin", os.urandom(min_bytes))
    data = doc.tobytes()
    doc.close()
    return data


def test_default_hosted_file_limit_is_50_mb():
    assert settings.public_max_file_mb == 50
    assert settings.public_max_pages == 5


def test_pdf_over_8_mb_is_accepted_without_calling_a_model(monkeypatch):
    adapter = MockAdapter()
    monkeypatch.setattr(main, "get_adapter", lambda: adapter)
    blob = padded_pdf(9 * 1024 * 1024)
    assert len(blob) > 8 * 1024 * 1024
    client = TestClient(main.app)
    created = client.post("/api/v1/jobs", files=[("files", ("archive.pdf", blob, "application/pdf"))])
    assert created.status_code == 200, created.text
    doc = created.json()["documents"][0]
    assert doc["status"] == "queued"
    finished = wait_done(client, created.json()["job_id"])[0]
    assert finished["status"] == "done"
    page = client.get(f"/api/v1/jobs/{created.json()['job_id']}/documents/{doc['doc_id']}").json()["pages"][0]
    assert page["source"] == "text_layer"
    assert "Born digital archive note 1824." in page["text"]
    assert adapter.calls == []  # text layer does not call the model


def test_pdf_over_50_mb_is_rejected_and_not_kept():
    blob = padded_pdf(51 * 1024 * 1024)
    assert len(blob) > 50 * 1024 * 1024
    client = TestClient(main.app)
    created = client.post("/api/v1/jobs", files=[("files", ("too-big.pdf", blob, "application/pdf"))])
    doc = created.json()["documents"][0]
    assert doc["status"] == "rejected"
    assert "50 MB" in doc["error"]
    job = created.json()["job_id"]
    assert list((settings.data_dir / "jobs" / job).rglob("source.*")) == []


def test_long_pdf_is_kept_and_only_a_chosen_range_is_read(monkeypatch):
    monkeypatch.setattr(main, "get_adapter", lambda: MockAdapter())
    client = TestClient(main.app)
    created = client.post("/api/v1/jobs", files=[("files", ("long.pdf", make_scan_pdf(6), "application/pdf"))])
    doc = created.json()["documents"][0]
    assert doc["status"] == "needs_range"
    assert doc["total_pages"] == 6 and doc["pages"] == 0
    assert "6 pages" in doc["error"] and "5" in doc["error"]
    job = created.json()["job_id"]
    assert list((settings.data_dir / "jobs" / job).rglob("source.*"))  # original kept
    too_wide = client.post(
        f"/api/v1/jobs/{job}/documents/{doc['doc_id']}/ocr",
        json={"pages": "1-6"},
    )
    assert too_wide.status_code == 400
    assert "6 pages" in too_wide.text
    assert list((settings.data_dir / "jobs" / job).rglob("source.*"))
    started = client.post(
        f"/api/v1/jobs/{job}/documents/{doc['doc_id']}/ocr",
        json={"pages": "1-2"},
    )
    assert started.status_code == 200 and started.json()["pages"] == 2
    finished = wait_done(client, job)[0]
    assert finished["total_pages"] == 6
    detail = client.get(f"/api/v1/jobs/{job}/documents/{doc['doc_id']}").json()
    assert [p["status"] for p in detail["pages"]] == ["done", "done", "skipped", "skipped", "skipped", "skipped"]
