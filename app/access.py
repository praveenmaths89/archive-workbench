"""Session isolation, upload limits, and file-path checks for a shared server."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import store
from .config import settings

log = logging.getLogger("access")

COOKIE = "aw_session"
ID_RE = re.compile(r"^[a-f0-9]{12}$")
VISITOR_RE = re.compile(r"^[a-f0-9]{32}$")
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_KEY_IN_TEXT = re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}")
_SECRET_LOCK = threading.Lock()
_SECRETS: dict[str, bytes] = {}
SENSITIVE_KEYS = {"api_key", "anthropic_api_key", "token", "password", "authorization", "secret"}


def redact(text: str) -> str:
    """Remove the server API key from anything that might be stored or returned."""
    secret = settings.anthropic_api_key or ""
    if secret and len(secret) >= 8:
        text = text.replace(secret, "[redacted]")
    return _KEY_IN_TEXT.sub("[redacted]", text)


def assert_safe_host(password: str = "") -> None:
    """A platform-assigned PORT means this process is reachable beyond one laptop."""
    if os.environ.get("PORT") and not settings.shared and not password:
        raise RuntimeError(
            "Refusing to start: PORT is set, neither HOSTED_MODE nor PUBLIC_MODE is on, "
            "and APP_PASSWORD is empty. Set HOSTED_MODE=1 for the full shared server, "
            "PUBLIC_MODE=1 for local OCR only, or APP_PASSWORD for a private server."
        )


def session_secret() -> bytes:
    if settings.session_secret:
        return settings.session_secret.encode()
    key = str(Path(settings.data_dir))
    with _SECRET_LOCK:
        cached = _SECRETS.get(key)
        if cached:
            return cached
        path = settings.data_dir / ".session_secret"
        if path.is_file() and path.stat().st_size >= 32:
            secret = path.read_bytes().strip()
        else:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            secret = secrets.token_hex(32).encode()
            path.write_bytes(secret)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        _SECRETS[key] = secret
        return secret


def mint_token() -> str:
    visitor = secrets.token_hex(16)
    exp = int(time.time()) + 7 * 24 * 3600
    body = f"v1.{visitor}.{exp}"
    sig = hmac.new(session_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def parse_token(token: str | None) -> str | None:
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != "v1":
        return None
    body = ".".join(parts[:3])
    expected = hmac.new(session_secret(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(parts[3], expected):
        return None
    visitor, exp = parts[1], parts[2]
    if not VISITOR_RE.fullmatch(visitor):
        return None
    try:
        if int(exp) < time.time():
            return None
    except ValueError:
        return None
    return visitor


def same_id(a: str | None, b: str | None) -> bool:
    if not a or not b or len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def safe_filename(name: str | None) -> str:
    base = Path(name or "upload").name.replace("\x00", "")
    base = _SAFE.sub("_", base).strip("._")[:120]
    return base or "upload"


def safe_stem(name: str | None) -> str:
    stem = Path(safe_filename(name)).stem
    stem = _SAFE.sub("_", stem).strip("._")[:80]
    return stem or "document"


def scrub_options(value):
    """Drop anything that looks like a credential before it is stored."""
    if isinstance(value, dict):
        return {k: scrub_options(v) for k, v in value.items() if str(k).lower() not in SENSITIVE_KEYS}
    if isinstance(value, list):
        return [scrub_options(v) for v in value[:100]]
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def contained_file(path: str | None, root: Path | None = None) -> Path | None:
    if not path:
        return None
    root = (root or settings.data_dir).resolve()
    try:
        candidate = Path(path).resolve()
    except OSError:
        return None
    if not candidate.is_file() or not candidate.is_relative_to(root):
        return None
    if candidate.suffix.lower() not in {".jpg", ".jpeg"}:
        return None
    return candidate


def require_job(job_id: str, visitor: str | None):
    if not ID_RE.fullmatch(job_id or ""):
        raise HTTPException(404, "job not found")
    job, docs = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if settings.shared and not same_id(job.get("visitor_id"), visitor):
        raise HTTPException(404, "job not found")
    return job, docs


def require_doc(job_id: str, doc_id: str, visitor: str | None):
    job, _docs = require_job(job_id, visitor)
    if not ID_RE.fullmatch(doc_id or ""):
        raise HTTPException(404, "document not found")
    doc = store.get_document(doc_id)
    if not doc or doc["job_id"] != job_id:
        raise HTTPException(404, "document not found")
    return job, doc


def _day_ago() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()


def _hour_ago() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def pages_remaining(visitor: str) -> int:
    used = store.pages_since(visitor, _day_ago())
    return max(0, settings.public_max_pages_per_day - used)


def enforce_new_job(visitor: str | None) -> None:
    if not settings.shared:
        return
    if not visitor:
        raise HTTPException(403, "This public server could not start a private session.")
    purge_expired()
    if store.inflight(visitor):
        raise HTTPException(429, "A document is still being read. Wait for it to finish before uploading another.")
    if store.count_jobs(visitor) >= settings.public_max_jobs:
        raise HTTPException(429, f"This session already has {settings.public_max_jobs} uploads. Delete one, or wait for them to expire.")
    if store.jobs_since(visitor, _hour_ago()) >= settings.public_max_jobs_per_hour:
        raise HTTPException(429, "Hourly upload limit reached for this session. Try again later.")
    if pages_remaining(visitor) <= 0:
        raise HTTPException(429, "Daily page limit reached for this session.")


def delete_job_files(job_id: str) -> None:
    if not ID_RE.fullmatch(job_id or ""):
        return
    root = (settings.data_dir / "jobs").resolve()
    target = (root / job_id).resolve()
    if target.is_relative_to(root):
        shutil.rmtree(target, ignore_errors=True)
    store.delete_job_rows(job_id)


def purge_expired() -> None:
    """Remove aged visitor uploads. Jobs with no visitor id are personal data and are kept."""
    if not settings.shared:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.public_retention_hours)
    for job_id, created, visitor_id in store.iter_jobs():
        if not visitor_id:
            continue
        try:
            when = datetime.fromisoformat(created)
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when < cutoff:
            delete_job_files(job_id)


def cookie_header(token: str) -> str:
    probe = Response()
    probe.set_cookie(
        COOKIE, token, max_age=7 * 24 * 3600, httponly=True, samesite="lax",
        secure=settings.cookie_secure, path="/",
    )
    for key, value in probe.raw_headers:
        if key.lower() == b"set-cookie":
            return value.decode()
    raise RuntimeError("could not build session cookie")


class SecurityMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        minted = None
        if settings.shared:
            visitor = parse_token(request.cookies.get(COOKIE))
            if visitor is None:
                minted = mint_token()
                visitor = parse_token(minted)
        else:
            visitor = None
        state = scope.setdefault("state", {})
        state["visitor"] = visitor

        async def send_wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if minted:
                    headers.append("set-cookie", cookie_header(minted))
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Frame-Options"] = "DENY"
                headers["Cross-Origin-Resource-Policy"] = "same-origin"
                headers["Content-Security-Policy"] = (
                    "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
                    "script-src 'self' 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; "
                    "form-action 'self'; connect-src 'self'"
                )
                path = scope.get("path") or ""
                if path == "/" or path.startswith("/api/"):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_wrapped)
