"""The shared server must not expose one visitor's documents, or the owner's API key, to another."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import access, adapters, main, store
from app.config import settings
from tests.test_pipeline import make_scan_pdf, make_text_pdf, wait_done


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "use_mock", True)
    monkeypatch.setattr(settings, "public_mode", False)


def _public(monkeypatch):
    monkeypatch.setattr(settings, "public_mode", True)
    monkeypatch.setattr(settings, "cookie_secure", False)


def test_tsv_groups_words_on_one_line():
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t90\tKittur\n"
        "5\t1\t1\t1\t1\t2\t20\t0\t10\t10\t80\tfort\n"
        "5\t1\t1\t1\t1\t3\t40\t0\t10\t10\t-1\t\n"
    )
    blocks, conf = adapters.blocks_from_tsv(tsv)
    assert blocks[0].text == "Kittur fort"
    assert conf == 0.85


def test_hosted_process_refuses_open_private_mode(monkeypatch):
    monkeypatch.setenv("PORT", "7860")
    with pytest.raises(RuntimeError):
        access.assert_safe_host("")


def test_hosted_process_allows_public_mode(monkeypatch):
    monkeypatch.setenv("PORT", "7860")
    _public(monkeypatch)
    access.assert_safe_host("")
    client = TestClient(main.app)
    assert client.get("/healthz").status_code == 200


def test_visitors_cannot_read_each_other(monkeypatch):
    _public(monkeypatch)
    owner = TestClient(main.app)
    other = TestClient(main.app)
    created = owner.post("/api/v1/jobs", files=[("files", ("note.pdf", make_text_pdf(), "application/pdf"))])
    assert created.status_code == 200, created.text
    job = created.json()["job_id"]
    doc = wait_done(owner, job)[0]["id"]
    assert owner.get(f"/api/v1/jobs/{job}").status_code == 200
    assert other.get(f"/api/v1/jobs/{job}").status_code == 404
    assert other.get(f"/api/v1/jobs/{job}/documents/{doc}").status_code == 404
    assert other.get(f"/api/v1/jobs/{job}/documents/{doc}/pages/1/image").status_code == 404
    assert other.get(f"/api/v1/jobs/{job}/documents/{doc}/download").status_code == 404
    assert other.delete(f"/api/v1/jobs/{job}").status_code == 404
    assert owner.get(f"/api/v1/jobs/{job}").status_code == 200

    listed = owner.get("/api/v1/jobs").json()
    assert [row["id"] for row in listed] == [job]
    assert "visitor_id" not in listed[0] and "options" not in listed[0]
    assert other.get("/api/v1/jobs").json() == []

    cookie = created.headers["set-cookie"]
    assert "aw_session=" in cookie and "httponly" in cookie.lower()
    forged = cookie.split(";", 1)[0].split("=", 1)[1]
    other.cookies.set("aw_session", forged[:-8] + "00000000")
    assert other.get(f"/api/v1/jobs/{job}").status_code == 404
    assert owner.get(f"/api/v1/jobs/not-an-id").status_code == 404


def test_public_mode_hides_api_key_and_refuses_research(monkeypatch):
    _public(monkeypatch)
    monkeypatch.setattr(settings, "use_mock", False)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-SECRETVALUE")

    def boom(self, *args, **kwargs):
        raise AssertionError("public mode constructed the paid client")

    monkeypatch.setattr(adapters.ClaudeAdapter, "__init__", boom)
    client = TestClient(main.app)
    models = client.get("/api/v1/models")
    assert models.status_code == 200
    assert "SECRETVALUE" not in models.text
    assert models.json()["api_key_configured"] is False
    assert models.json()["research_enabled"] is False
    assert models.json()["mode"] == "local"

    created = client.post("/api/v1/jobs", files=[("files", ("born.pdf", make_text_pdf(), "application/pdf"))])
    job = created.json()["job_id"]
    doc = wait_done(client, job)[0]
    assert doc["status"] == "done"
    detail = client.get(f"/api/v1/jobs/{job}/documents/{doc['id']}").json()
    assert detail["pages"][0]["source"] == "text_layer"
    assert "Born digital" in detail["pages"][0]["text"]
    assert "SECRETVALUE" not in client.get(f"/api/v1/jobs/{job}").text
    research = client.post(f"/api/v1/jobs/{job}/documents/{doc['id']}/research", json={"question": "Who?"})
    assert research.status_code == 403
    assert "SECRETVALUE" not in research.text

    scan = client.post("/api/v1/jobs", files=[("files", ("scan.pdf", make_scan_pdf(1), "application/pdf"))])
    # A second upload in the same hour is allowed; this one must not call Claude even if Tesseract is absent.
    assert scan.status_code == 200
    scan_doc = wait_done(client, scan.json()["job_id"])[0]
    body = client.get(f"/api/v1/jobs/{scan.json()['job_id']}/documents/{scan_doc['id']}").text
    assert "SECRETVALUE" not in body
    assert "claude" not in body.lower()


def test_public_rerun_ignores_requested_paid_model(monkeypatch):
    _public(monkeypatch)
    client = TestClient(main.app)
    job = client.post("/api/v1/jobs", files=[("files", ("s.pdf", make_scan_pdf(1), "application/pdf"))]).json()["job_id"]
    doc = wait_done(client, job)[0]["id"]
    rerun = client.post(
        f"/api/v1/jobs/{job}/documents/{doc}/pages/1/rerun",
        json={"model": "claude-opus-5-5"},
    )
    assert rerun.status_code == 200
    assert rerun.json()["routing"]["model"] == "tesseract"


def test_public_limits_and_filename(monkeypatch):
    _public(monkeypatch)
    monkeypatch.setattr(settings, "public_max_file_mb", 1)
    monkeypatch.setattr(settings, "public_max_pages", 1)
    client = TestClient(main.app)
    huge = b"%PDF-1.4\n" + b"0" * (2 * 1024 * 1024)
    rejected = client.post("/api/v1/jobs", files=[("files", ("big.pdf", huge, "application/pdf"))])
    assert rejected.json()["documents"][0]["status"] == "rejected"

    too_many = client.post("/api/v1/jobs", files=[("files", ("s.pdf", make_scan_pdf(2), "application/pdf"))])
    held = too_many.json()["documents"][0]
    assert held["status"] == "needs_range" and held["total_pages"] == 2
    assert "2 pages" in held["error"] and (settings.data_dir / "jobs" / too_many.json()["job_id"]).exists()

    tricky = client.post(
        "/api/v1/jobs",
        data={"options": json.dumps({"anthropic_api_key": "sk-ant-SECRETVALUE", "pages": "1"})},
        files=[("files", ("../../etc/passwd.pdf", make_text_pdf(), "application/pdf"))],
    )
    assert tricky.status_code == 200
    doc = tricky.json()["documents"][0]
    assert doc["filename"] == "passwd.pdf"
    assert "SECRETVALUE" not in store.get_job(tricky.json()["job_id"])[0]["options"]
    wait_done(client, tricky.json()["job_id"])
    header = client.get(
        f"/api/v1/jobs/{tricky.json()['job_id']}/documents/{doc['doc_id']}/download?format=txt"
    ).headers["content-disposition"]
    assert "\n" not in header and ".." not in header


def test_quota_and_password_bypass(monkeypatch):
    _public(monkeypatch)
    monkeypatch.setattr(settings, "public_max_jobs", 1)
    monkeypatch.setattr(main.auth_cfg, "app_password", "secret")
    client = TestClient(main.app)
    assert client.get("/api/v1/models").status_code == 200  # public mode is anonymous
    first = client.post("/api/v1/jobs", files=[("files", ("a.pdf", make_text_pdf(), "application/pdf"))])
    assert first.status_code == 200
    wait_done(client, first.json()["job_id"])
    second = client.post("/api/v1/jobs", files=[("files", ("b.pdf", make_text_pdf(), "application/pdf"))])
    assert second.status_code == 429


def test_purge_keeps_personal_jobs(tmp_path, monkeypatch):
    _public(monkeypatch)
    personal = store.create_job("{}", visitor_id=None)
    (settings.data_dir / "jobs" / personal).mkdir(parents=True)
    (settings.data_dir / "jobs" / personal / "keep.txt").write_text("owner")
    visitor_job = store.create_job("{}", visitor_id="ab" * 16)
    (settings.data_dir / "jobs" / visitor_job).mkdir(parents=True)
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    store.touch_job_created(personal, old)
    store.touch_job_created(visitor_job, old)
    access.purge_expired()
    assert (settings.data_dir / "jobs" / personal / "keep.txt").is_file()
    assert store.get_job(personal)[0] is not None
    assert not (settings.data_dir / "jobs" / visitor_job).exists()
    assert store.get_job(visitor_job)[0] is None
    access.delete_job_files("..")
    access.delete_job_files("../escape")
    assert (settings.data_dir / "jobs" / personal / "keep.txt").is_file()


def test_page_image_cannot_escape_the_job_directory(monkeypatch):
    _public(monkeypatch)
    client = TestClient(main.app)
    job = client.post("/api/v1/jobs", files=[("files", ("s.pdf", make_text_pdf(), "application/pdf"))]).json()["job_id"]
    doc = wait_done(client, job)[0]["id"]
    ir = main.load_ir(job, doc)
    ir.pages[0].image_path = "/etc/passwd"
    (settings.data_dir / "jobs" / job / doc / "ir.json").write_text(ir.model_dump_json())
    image = client.get(f"/api/v1/jobs/{job}/documents/{doc}/pages/1/image")
    assert image.status_code == 200  # preview is rendered from the source, not the poisoned path
    assert b"root:" not in image.content
    pdf = client.get(f"/api/v1/jobs/{job}/documents/{doc}/download?format=pdf")
    assert pdf.status_code == 200 and b"root:" not in pdf.content
