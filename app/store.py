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
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created TEXT, options TEXT);
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
            yield con
            con.commit()
        finally:
            con.close()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def create_job(options: str) -> str:
    jid = new_id()
    with db() as c:
        c.execute("INSERT INTO jobs VALUES (?,?,?)", (jid, datetime.now(timezone.utc).isoformat(), options))
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


def list_jobs(limit=50):
    with db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,))]
