"""Google sign-in, the allowlist, and the session cookie."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import AccessEntry, UserSession

log = logging.getLogger("auth")

COOKIE = "aw_session"
STATE_COOKIE = "aw_oauth_state"
SESSION_DAYS = 14


def split_list(value: str) -> list[str]:
    return [part.strip().lower() for part in (value or "").replace(";", ",").split(",") if part.strip()]


def redirect_uri() -> str:
    return settings.app_base_url.rstrip("/") + "/api/auth/callback"


def _secret() -> bytes:
    if settings.auth_secret.strip():
        return settings.auth_secret.strip().encode()
    path = settings.data_dir / "auth_secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip().encode()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign_state(state: str) -> str:
    sig = hmac.new(_secret(), state.encode(), hashlib.sha256).hexdigest()
    return f"{state}.{sig}"


def state_matches(cookie: str | None, state: str) -> bool:
    if not cookie or not state or "." not in cookie:
        return False
    raw, sig = cookie.rsplit(".", 1)
    if not hmac.compare_digest(raw, state):
        return False
    expected = hmac.new(_secret(), state.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def cookie_secure() -> bool:
    return settings.app_base_url.lower().startswith("https://")


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        max_age=SESSION_DAYS * 24 * 3600,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def seed_access(session: Session) -> None:
    """Insert environment emails if they are missing. Local edits are kept."""
    admins = split_list(settings.admin_emails) or ["praveenmaths89@gmail.com"]

    def add(kind: str, value: str, is_admin: bool) -> None:
        value = value.strip().lower().lstrip("@")
        if not value:
            return
        existing = session.scalar(
            select(AccessEntry).where(AccessEntry.kind == kind, AccessEntry.value == value)
        )
        if existing is None:
            session.add(AccessEntry(kind=kind, value=value, is_admin=is_admin, source="env"))
        elif is_admin and not existing.is_admin:
            existing.is_admin = True

    for email in admins:
        add("email", email, True)
    for email in split_list(settings.allowed_emails):
        add("email", email, False)
    for domain in split_list(settings.allowed_domains):
        add("domain", domain, False)
    session.commit()


def email_allowed(session: Session, email: str) -> tuple[bool, bool]:
    email = email.strip().lower()
    domain = email.split("@", 1)[-1] if "@" in email else ""
    allowed = False
    is_admin = False
    rows = session.scalars(select(AccessEntry)).all()
    for row in rows:
        if row.kind == "email" and row.value == email:
            allowed = True
            is_admin = is_admin or row.is_admin
        elif row.kind == "domain" and row.value == domain:
            allowed = True
    return allowed, is_admin


def admin_count(session: Session) -> int:
    return session.scalar(
        select(func.count()).select_from(AccessEntry).where(AccessEntry.is_admin.is_(True))
    ) or 0


def exchange_code(code: str) -> dict:
    """Trade Google's code for a verified email. Tests replace this function."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise RuntimeError("Google client id and secret are not set")
    token = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    token.raise_for_status()
    id_token = token.json().get("id_token")
    if not id_token:
        raise RuntimeError("Google did not return an id token")
    info = httpx.get(
        "https://oauth2.googleapis.com/tokeninfo",
        params={"id_token": id_token},
        timeout=20,
    )
    info.raise_for_status()
    data = info.json()
    if data.get("aud") != settings.google_client_id:
        raise RuntimeError("Google token was not issued for this app")
    if str(data.get("email_verified", "")).lower() not in ("true", "1"):
        raise RuntimeError("Google email is not verified")
    email = (data.get("email") or "").strip().lower()
    if not email:
        raise RuntimeError("Google did not return an email")
    return {"email": email, "name": data.get("name") or ""}


def login_redirect() -> tuple[str, str]:
    state = secrets.token_urlsafe(24)
    query = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}", state


def read_user(request: Request, session: Session) -> dict | None:
    if settings.auth_disabled:
        return {"email": None, "is_admin": True, "auth_disabled": True, "authenticated": True}
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    row = session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row is None or row.expires_at <= datetime.now(timezone.utc):
        return None
    return {
        "email": row.email,
        "is_admin": row.is_admin,
        "auth_disabled": False,
        "authenticated": True,
    }


def require_admin(user: dict) -> None:
    if not user.get("is_admin"):
        raise HTTPException(403, "Only an admin can change this.")


def open_session(session: Session, email: str, is_admin: bool) -> str:
    token = secrets.token_urlsafe(32)
    session.add(UserSession(
        token_hash=hash_token(token),
        email=email,
        is_admin=is_admin,
        expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
    ))
    session.commit()
    return token


def drop_session(session: Session, token: str | None) -> None:
    if not token:
        return
    row = session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row is not None:
        session.delete(row)
        session.commit()
