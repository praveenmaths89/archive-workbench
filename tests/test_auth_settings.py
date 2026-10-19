"""Google allowlist and the Settings key. Token exchange is mocked."""
from __future__ import annotations

from archive_workbench.auth import hash_token
from archive_workbench.config import settings
from archive_workbench.models import UserSession
from datetime import datetime, timedelta, timezone


def test_auth_disabled_allows_the_api(client):
    assert client.get("/api/health").json()["auth_disabled"] is True
    assert client.get("/api/documents").status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["authenticated"] is True and me["is_admin"] is True


def test_allowlisted_email_gets_a_session_and_others_do_not(client, monkeypatch):
    settings.auth_disabled = False
    settings.google_client_id = "client"
    settings.google_client_secret = "secret"
    try:
        def exchange(code: str) -> dict:
            if code == "ok":
                return {"email": "praveenmaths89@gmail.com", "name": "Praveen"}
            return {"email": "stranger@example.com", "name": "No"}

        monkeypatch.setattr("archive_workbench.auth.exchange_code", exchange)
        start = client.get("/api/auth/login", follow_redirects=False)
        assert start.status_code in (302, 307)
        assert "accounts.google.com" in start.headers["location"]
        state = start.headers["location"].split("state=")[1].split("&")[0]

        allowed = client.get("/api/auth/callback", params={"code": "ok", "state": state}, follow_redirects=False)
        assert allowed.status_code in (302, 307)
        assert allowed.headers["location"].rstrip("/") == "http://localhost:3000"
        assert client.get("/api/documents").status_code == 200

        client.cookies.clear()
        start = client.get("/api/auth/login", follow_redirects=False)
        state = start.headers["location"].split("state=")[1].split("&")[0]
        refused = client.get(
            "/api/auth/callback", params={"code": "no", "state": state}, follow_redirects=False,
        )
        assert refused.status_code in (302, 307)
        assert "/access-denied" in refused.headers["location"]
        assert "stranger%40example.com" in refused.headers["location"]
        assert client.get("/api/documents").status_code == 401
    finally:
        settings.auth_disabled = True
        client.cookies.clear()


def test_settings_masks_and_clears_a_key_and_blocks_non_admins(client):
    saved = client.put("/api/settings", json={
        "provider": "anthropic",
        "model": "anthropic/claude-sonnet-4-5",
        "api_key": "sk-test-secret-1234",
        "ocr_engine": "tesseract",
    })
    assert saved.status_code == 200
    body = saved.json()
    assert body["key_source"] == "saved"
    assert body["key_mask"].endswith("1234")
    assert "sk-test-secret" not in body["key_mask"]
    assert "sk-test-secret-1234" not in saved.text

    cleared = client.delete("/api/settings/key")
    assert cleared.status_code == 200
    assert cleared.json()["key_source"] == "none"
    assert cleared.json()["key_set"] is False

    settings.auth_disabled = False
    try:
        token = "reader-token"
        from archive_workbench.db import session as open_session
        with open_session() as db:
            db.add(UserSession(
                token_hash=hash_token(token),
                email="reader@example.com",
                is_admin=False,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ))
            db.commit()
        client.cookies.clear()
        denied = client.put(
            "/api/settings",
            json={"api_key": "sk-nope-9999"},
            cookies={"aw_session": token},
        )
        assert denied.status_code == 403
    finally:
        settings.auth_disabled = True


def test_claude_without_a_key_falls_back_to_tesseract(client):
    from tests.test_api import _scan_pdf
    from archive_workbench.worker import drain

    response = client.post(
        "/api/documents",
        data={"options": '{"ocr_engine": "claude"}'},
        files=[("files", ("scan.pdf", _scan_pdf(), "application/pdf"))],
    )
    doc_id = response.json()["documents"][0]["id"]
    drain()
    detail = client.get(f"/api/documents/{doc_id}").json()
    assert detail["pages"][0]["ocr_engine"] == "tesseract"
    assert "Tesseract" in (detail["progress"] or "")
