"""Upload, OCR, ask, note, translate, export. The worker runs in-process."""
from __future__ import annotations

import io
import threading
import time

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import text

from archive_workbench.db import engine, session
from archive_workbench.queue import enqueue
from archive_workbench.worker import drain


def _scan_pdf(text: str = "Kittur revenue minute") -> bytes:
    image = Image.new("RGB", (1400, 360), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 72)
    draw.text((48, 120), text, fill="black", font=font)
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    doc = pymupdf.open()
    page = doc.new_page(width=500, height=140)
    page.insert_image(page.rect, stream=buf.getvalue())
    data = doc.tobytes()
    doc.close()
    return data


def _text_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 540, 760), "Born digital minute about Dharwar revenue. " * 20)
    data = doc.tobytes()
    doc.close()
    return data


def test_health(client):
    body = client.get("/api/health").json()
    assert body["database"] is True
    assert body["llm"] is False
    assert body["embedding"] == "hash"
    assert body["ocr_engine"] == "tesseract"
    assert body["max_file_mb"] == 500


def test_reject_bad_file_and_keep_the_batch(client):
    files = [
        ("files", ("scan.pdf", _scan_pdf(), "application/pdf")),
        ("files", ("bad.pdf", b"not a pdf", "application/pdf")),
    ]
    response = client.post("/api/documents", files=files)
    assert response.status_code == 200
    docs = {row["filename"]: row for row in response.json()["documents"]}
    assert docs["bad.pdf"]["status"] == "rejected"
    assert docs["scan.pdf"]["status"] == "queued"
    assert drain() >= 1
    detail = client.get(f"/api/documents/{docs['scan.pdf']['id']}").json()
    assert detail["status"] in ("done", "done_with_errors")
    text = " ".join(page["text"] for page in detail["pages"])
    assert "Kittur" in text
    assert any(region["w"] > 0 for region in detail["regions"])


def test_text_layer_pdf_skips_tesseract(client):
    response = client.post("/api/documents", files=[("files", ("born.pdf", _text_pdf(), "application/pdf"))])
    doc_id = response.json()["documents"][0]["id"]
    drain()
    detail = client.get(f"/api/documents/{doc_id}").json()
    assert detail["pages"][0]["ocr_engine"] == "text_layer"
    assert "Dharwar" in detail["pages"][0]["text"]


def test_ask_cites_a_page_region_and_exports(client, monkeypatch):
    from archive_workbench import agent
    monkeypatch.setattr(agent, "_library_hits", lambda *a, **k: [{
        "source": "internet_archive",
        "title": "Kittur papers",
        "url": "https://archive.org/details/kittur",
        "description": "Related volume",
    }])
    response = client.post("/api/documents", files=[("files", ("scan.pdf", _scan_pdf(), "application/pdf"))])
    doc_id = response.json()["documents"][0]["id"]
    drain()
    asked = client.post(f"/api/documents/{doc_id}/ask", json={"question": "What place does this minute name?"})
    assert asked.status_code == 200
    drain()
    messages = client.get(f"/api/documents/{doc_id}/messages").json()
    assistant = [m for m in messages if m["role"] == "assistant"][-1]
    doc_cites = [c for c in assistant["citations"] if c["kind"] == "document"]
    lib_cites = [c for c in assistant["citations"] if c["kind"] == "library"]
    assert doc_cites and doc_cites[0]["page"] == 1 and doc_cites[0]["region_id"]
    assert f"[{doc_cites[0]['n']}]" in assistant["content"]
    assert lib_cites and lib_cites[0]["url"].startswith("https://archive.org")
    assert "Kittur" in assistant["content"]

    docx = client.get(f"/api/documents/{doc_id}/export?format=docx")
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    tei = client.get(f"/api/documents/{doc_id}/export?format=tei")
    assert tei.status_code == 200 and tei.content.startswith(b"<?xml")
    bib = client.get(f"/api/documents/{doc_id}/export?format=bibtex").text
    assert "@unpublished" in bib
    md = client.get(f"/api/documents/{doc_id}/export?format=md").text
    assert "Kittur" in md

    note = client.post(f"/api/documents/{doc_id}/notes", json={"body": "Check the folio number."})
    assert note.status_code == 200
    again = client.get(f"/api/documents/{doc_id}").json()
    assert again["notes"][0]["body"] == "Check the folio number."

    job = client.post(f"/api/documents/{doc_id}/translate", json={"language": "hi"}).json()
    drain()
    finished = client.get(f"/api/jobs/{job['job_id']}").json()
    assert finished["status"] == "done"
    page = client.get(f"/api/documents/{doc_id}").json()["pages"][0]
    assert page["translation_language"] == "hi"
    assert page["translation"].startswith("[mock translation to hi]")

    found = client.get("/api/search", params={"q": "Kittur", "document_id": doc_id}).json()
    assert found and found[0]["page"] == 1


def test_europeana_reports_not_configured(client, monkeypatch):
    from archive_workbench.config import settings
    monkeypatch.setattr(settings, "europeana_api_key", "")
    monkeypatch.setattr(settings, "dpla_api_key", "")

    def boom(self, query, limit=8):
        raise AssertionError("a missing key must not call the network")

    monkeypatch.setattr("archive_workbench.connectors.europeana.Europeana.search", boom)
    monkeypatch.setattr("archive_workbench.connectors.dpla.Dpla.search", boom)
    body = client.get("/api/library/search", params={"q": "Kittur", "sources": "europeana,dpla"}).json()
    assert {row["source"]: row["status"] for row in body["sources"]} == {
        "europeana": "not_configured",
        "dpla": "not_configured",
    }


def test_skip_locked_gives_each_worker_its_own_job(db):
    db_session = session()
    enqueue(db_session, "explain", {"n": 1})
    enqueue(db_session, "explain", {"n": 2})
    db_session.commit()
    db_session.close()

    found: list[str] = []
    lock = threading.Lock()
    start = threading.Barrier(2)

    def take():
        start.wait()
        own = session()
        row = own.execute(text(
            """
            UPDATE jobs SET status = 'running', locked_by = 't'
            WHERE id = (
              SELECT id FROM jobs WHERE status = 'queued'
              ORDER BY created_at
              FOR UPDATE SKIP LOCKED
              LIMIT 1
            )
            RETURNING id::text
            """
        )).first()
        with lock:
            if row:
                found.append(row[0])
        time.sleep(0.3)
        own.rollback()
        own.close()

    threads = [threading.Thread(target=take) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(found) == 2
    assert found[0] != found[1]
