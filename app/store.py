"""SQLite-backed job/document state. Page-level detail lives in each document's ir.json."""
from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import settings

_lock = threading.Lock()
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, created TEXT, options TEXT, visitor_id TEXT);
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, job_id TEXT, filename TEXT, kind TEXT, status TEXT,
  total_pages INTEGER DEFAULT 0, done_pages INTEGER DEFAULT 0, error TEXT);
"""


def _path():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.data_dir / "app.db"


@contextmanager
def db():
    with _lock:
        con = sqlite3.connect(_path())
        con.row_factory = sqlite3.Row
        con.executescript(SCHEMA)
        try:  # migrate databases created before page selection existed
            con.execute("ALTER TABLE documents ADD COLUMN selected_pages INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            con.execute("ALTER TABLE jobs ADD COLUMN visitor_id TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            yield con
            con.commit()
        finally:
            con.close()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def create_job(options: str, visitor_id: str | None = None) -> str:
    jid = new_id()
    with db() as c:
        c.execute(
            "INSERT INTO jobs (id, created, options, visitor_id) VALUES (?,?,?,?)",
            (jid, datetime.now(timezone.utc).isoformat(), options, visitor_id),
        )
    return jid


def add_document(job_id: str, filename: str, kind: str, status="queued", error=None) -> str:
    did = new_id()
    with db() as c:
        c.execute("INSERT INTO documents (id,job_id,filename,kind,status,error) VALUES (?,?,?,?,?,?)",
                  (did, job_id, filename, kind, status, error))
    return did


def update_document(doc_id: str, **fields):
    keys = ", ".join(f"{k}=?" for k in fields)
    with db() as c:
        c.execute(f"UPDATE documents SET {keys} WHERE id=?", (*fields.values(), doc_id))


def get_job(job_id: str):
    with db() as c:
        j = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        docs = c.execute("SELECT * FROM documents WHERE job_id=?", (job_id,)).fetchall()
    return (dict(j), [dict(d) for d in docs]) if j else (None, [])


def get_document(doc_id: str):
    with db() as c:
        r = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return dict(r) if r else None


def list_jobs(limit=50, visitor_id: str | None = None):
    with db() as c:
        if visitor_id is None:
            rows = c.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,))
        else:
            rows = c.execute(
                "SELECT * FROM jobs WHERE visitor_id=? ORDER BY created DESC LIMIT ?",
                (visitor_id, limit),
            )
        return [dict(r) for r in rows]


def count_jobs(visitor_id: str) -> int:
    with db() as c:
        return int(c.execute("SELECT COUNT(*) FROM jobs WHERE visitor_id=?", (visitor_id,)).fetchone()[0])


def jobs_since(visitor_id: str, since_iso: str) -> int:
    with db() as c:
        return int(c.execute(
            "SELECT COUNT(*) FROM jobs WHERE visitor_id=? AND created>=?",
            (visitor_id, since_iso),
        ).fetchone()[0])


def pages_since(visitor_id: str, since_iso: str) -> int:
    with db() as c:
        row = c.execute(
            """SELECT COALESCE(SUM(d.selected_pages), 0)
               FROM documents d JOIN jobs j ON j.id = d.job_id
               WHERE j.visitor_id=? AND j.created>=? AND d.status!='rejected'""",
            (visitor_id, since_iso),
        ).fetchone()
    return int(row[0] or 0)


def inflight(visitor_id: str) -> int:
    with db() as c:
        return int(c.execute(
            """SELECT COUNT(*) FROM documents d JOIN jobs j ON j.id = d.job_id
               WHERE j.visitor_id=? AND d.status IN ('queued', 'processing')""",
            (visitor_id,),
        ).fetchone()[0])


def iter_jobs():
    with db() as c:
        rows = c.execute("SELECT id, created, visitor_id FROM jobs").fetchall()
    return [(r["id"], r["created"], r["visitor_id"]) for r in rows]


def touch_job_created(job_id: str, created: str) -> None:
    with db() as c:
        c.execute("UPDATE jobs SET created=? WHERE id=?", (created, job_id))


def delete_job_rows(job_id: str) -> None:
    with db() as c:
        c.execute("DELETE FROM documents WHERE job_id=?", (job_id,))
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
