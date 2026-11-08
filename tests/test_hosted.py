"""Hosted mode keeps Claude OCR and web search on the server key, isolated per visitor."""
import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from app import access, adapters, main, research
from app.config import settings
from tests.test_pipeline import make_scan_pdf, make_text_pdf, wait_done

SECRET = "sk-ant-api03-TESTSECRETVALUEONLY"


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "use_mock", True)
    monkeypatch.setattr(settings, "hosted_mode", False)
    monkeypatch.setattr(settings, "public_mode", False)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "cookie_secure", False)


def _hosted(monkeypatch, key=SECRET):
    monkeypatch.setattr(settings, "hosted_mode", True)
    monkeypatch.setattr(settings, "use_mock", False)
    monkeypatch.setattr(settings, "anthropic_api_key", key)


def _files_contain(root, needle: str) -> bool:
    if not needle:
        return False
    for path in root.rglob("*"):
        if path.is_file() and needle.encode() in path.read_bytes():
            return True
    return False


class _Usage:
    input_tokens = 11
    output_tokens = 7


class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Msg:
    def __init__(self, text):
        self.content = [_Text(text)]
        self.usage = _Usage()


class _Messages:
    def __init__(self):
        self.kwargs = []

    def create(self, **kwargs):
        self.kwargs.append(kwargs)
        body = json.dumps({
            "language": "en",
            "confidence": 0.91,
            "blocks": [{"type": "paragraph", "text": "Kittur fort record", "confidence": 0.91}],
        })
        return _Msg(body)


class _Anthropic:
    seen = []

    def __init__(self, api_key, **kwargs):
        _Anthropic.seen.append(api_key)
        self.messages = _Messages()


def test_hosted_boot_is_allowed_on_a_platform_port(monkeypatch):
    monkeypatch.setenv("PORT", "10000")
    _hosted(monkeypatch)
    access.assert_safe_host("")
    assert TestClient(main.app).get("/healthz").status_code == 200


def test_hosted_ocr_uses_server_key_and_hides_it(monkeypatch, caplog):
    _hosted(monkeypatch)
    _Anthropic.seen = []
    monkeypatch.setattr("anthropic.Anthropic", _Anthropic)
    client = TestClient(main.app)
    models = client.get("/api/v1/models")
    assert models.json()["mode"] == "claude"
    assert models.json()["research_enabled"] is True
    assert SECRET not in models.text
    job = client.post("/api/v1/jobs", files=[("files", ("scan.png.pdf", make_scan_pdf(1), "application/pdf"))]).json()["job_id"]
    doc = wait_done(client, job)[0]
    detail = client.get(f"/api/v1/jobs/{job}/documents/{doc['id']}")
    assert "Kittur fort record" in detail.text
    assert "mock transcription" not in detail.text
    assert SECRET not in detail.text
    assert _Anthropic.seen == [SECRET]
    assert not _files_contain(settings.data_dir, SECRET)
    assert SECRET not in caplog.text


def test_hosted_without_key_refuses_instead_of_mock(monkeypatch):
    monkeypatch.setattr(settings, "hosted_mode", True)
    monkeypatch.setattr(settings, "use_mock", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    client = TestClient(main.app)
    body = client.get("/api/v1/models").json()
    assert body["mode"] == "unavailable"
    assert body["research_enabled"] is False
    assert body["api_key_configured"] is False
    job = client.post("/api/v1/jobs", files=[("files", ("scan.pdf", make_scan_pdf(1), "application/pdf"))]).json()["job_id"]
    doc = wait_done(client, job)[0]
    detail = client.get(f"/api/v1/jobs/{job}/documents/{doc['id']}")
    assert "mock transcription" not in detail.text
    assert "not configured" in detail.text.lower() or "not configured" in (doc.get("error") or "").lower()
    born = client.post("/api/v1/jobs", files=[("files", ("born.pdf", make_text_pdf(), "application/pdf"))]).json()["job_id"]
    born_doc = wait_done(client, born)[0]["id"]
    page = client.get(f"/api/v1/jobs/{born}/documents/{born_doc}").json()["pages"][0]
    assert page["source"] == "text_layer" and "Born digital" in page["text"]
    denied = client.post(f"/api/v1/jobs/{born}/documents/{born_doc}/research", json={"question": "Who?"})
    assert denied.status_code == 503
    assert "not configured" in denied.text.lower()


def test_hosted_research_and_isolation(monkeypatch, caplog):
    _hosted(monkeypatch)

    def fake_research(*args, **kwargs):
        assert SECRET not in json.dumps(args)
        return research.ResearchResult(answer_md="Cited fact [1]", sources=[research.Source(1, "https://archive.example/a", "Archive")], queries=["Kittur"])

    monkeypatch.setattr(main.research_mod, "run_research", fake_research)
    owner = TestClient(main.app)
    other = TestClient(main.app)
    job = owner.post("/api/v1/jobs", files=[("files", ("note.pdf", make_text_pdf(), "application/pdf"))]).json()["job_id"]
    doc = wait_done(owner, job)[0]["id"]
    started = owner.post(f"/api/v1/jobs/{job}/documents/{doc}/research", json={"question": "What happened?"})
    assert started.status_code == 200
    rid = started.json()["research_id"]
    for _ in range(50):
        rec = owner.get(f"/api/v1/research/{rid}")
        if rec.json().get("status") != "running":
            break
    report = rec.json()
    assert report["status"] == "done" and "Cited fact" in report["answer_md"]
    exported = owner.get(f"/api/v1/research/{rid}/download?format=md")
    assert "Cited fact" in exported.text
    assert SECRET not in rec.text and SECRET not in exported.text
    assert other.get(f"/api/v1/jobs/{job}").status_code == 404
    assert other.get(f"/api/v1/research/{rid}").status_code == 404
    assert other.get(f"/api/v1/research/{rid}/download?format=md").status_code == 404
    assert other.get("/api/v1/jobs").json() == []
    assert not _files_contain(settings.data_dir, SECRET)
    assert SECRET not in caplog.text


def test_hosted_error_redacts_the_server_key(monkeypatch, caplog):
    _hosted(monkeypatch)

    def explode(*args, **kwargs):
        raise RuntimeError(f"provider rejected {SECRET}")

    monkeypatch.setattr(main.research_mod, "run_research", explode)
    client = TestClient(main.app)
    job = client.post("/api/v1/jobs", files=[("files", ("note.pdf", make_text_pdf(), "application/pdf"))]).json()["job_id"]
    doc = wait_done(client, job)[0]["id"]
    rid = client.post(f"/api/v1/jobs/{job}/documents/{doc}/research", json={}).json()["research_id"]
    rec = {}
    for _ in range(50):
        rec = client.get(f"/api/v1/research/{rid}").json()
        if rec.get("status") != "running":
            break
    assert rec["status"] == "failed"
    assert SECRET not in json.dumps(rec)
    assert not _files_contain(settings.data_dir, SECRET)
    assert SECRET not in caplog.text


def test_research_client_receives_only_the_server_key(monkeypatch):
    _hosted(monkeypatch)
    seen = []

    class Client:
        def __init__(self, api_key, **kwargs):
            seen.append(api_key)
            raise RuntimeError("constructed")

    monkeypatch.setattr(research.anthropic, "Anthropic", Client)
    with pytest.raises(RuntimeError, match="constructed"):
        research._client()
    assert seen == [SECRET]
