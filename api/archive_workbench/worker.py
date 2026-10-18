"""Separate worker process. Claims jobs with SKIP LOCKED."""
from __future__ import annotations

import logging
import os
import socket
import time
import uuid

from sqlalchemy import text

from .agent import run_ask
from .db import engine, session
from .models import Document, Job, Message
from .ocr import FatalProviderError
from .pipeline import queue_followups, run_embed, run_explain, run_ocr, run_translate
from .queue import claim, fail, finish, reclaim_stale

log = logging.getLogger("worker")


def wait_for_schema(attempts: int = 60) -> None:
    for _ in range(attempts):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1 FROM jobs LIMIT 1"))
            return
        except Exception:
            time.sleep(1)
    raise SystemExit("database schema is not ready (jobs table missing)")


def _handle(db, job: Job) -> dict | None:
    payload = job.payload or {}
    if job.kind == "ocr":
        try:
            result = run_ocr(db, job.document_id, payload)
        except FatalProviderError as exc:
            doc = db.get(Document, job.document_id)
            if doc is not None:
                doc.status = "failed"
                doc.error = str(exc)
                db.commit()
            result = {"fatal": str(exc)}
        if job.document_id:
            queue_followups(db, job.document_id)
        return result
    if job.kind == "embed":
        return run_embed(db, job.document_id)
    if job.kind == "explain":
        return run_explain(db, job.document_id)
    if job.kind == "translate":
        return run_translate(db, job.document_id, payload.get("language") or "hi")
    if job.kind == "ask":
        result = run_ask(db, job.document_id, payload.get("question") or "")
        db.add(Message(
            document_id=job.document_id,
            role="assistant",
            content=result["content"],
            citations=result["citations"],
            dropped=result["dropped"],
        ))
        db.commit()
        return {"mock": result["mock"], "citations": len(result["citations"])}
    raise RuntimeError(f"unknown job kind {job.kind}")


def process_one(worker_id: str = "worker") -> bool:
    db = session()
    jid: uuid.UUID | None = None
    try:
        reclaim_stale(db)
        jid = claim(db, worker_id)
        if jid is None:
            return False
        job = db.get(Job, jid)
        try:
            result = _handle(db, job)
            job = db.get(Job, jid)
            finish(db, job, result)
        except Exception as exc:
            log.exception("job %s failed", jid)
            db.rollback()
            job = db.get(Job, jid)
            fail(db, job, exc)
            if job is not None and job.status == "failed" and job.document_id and job.kind in ("ocr", "embed"):
                doc = db.get(Document, job.document_id)
                if doc is not None and doc.status in ("queued", "processing"):
                    doc.status = "failed"
                    doc.error = job.error
                    db.commit()
        return True
    finally:
        db.close()


def drain(max_jobs: int = 40, worker_id: str = "test") -> int:
    done = 0
    while done < max_jobs and process_one(worker_id):
        done += 1
    return done


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    log.info("worker %s waiting for schema", worker_id)
    wait_for_schema()
    log.info("worker %s ready", worker_id)
    while True:
        if not process_one(worker_id):
            time.sleep(0.5)


if __name__ == "__main__":
    main()
