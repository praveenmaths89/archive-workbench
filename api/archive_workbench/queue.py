"""Postgres job queue. Claimed with FOR UPDATE SKIP LOCKED. No Redis."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import Job


def enqueue(session: Session, kind: str, payload: dict | None = None,
            document_id: uuid.UUID | None = None) -> Job:
    job = Job(kind=kind, payload=payload or {}, document_id=document_id, status="queued")
    session.add(job)
    session.flush()
    return job


def claim(session: Session, worker_id: str) -> uuid.UUID | None:
    stmt = (
        select(Job)
        .where(Job.status == "queued", Job.run_after <= datetime.now(timezone.utc), Job.attempts < Job.max_attempts)
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = session.scalars(stmt).first()
    if job is None:
        session.rollback()
        return None
    job.status = "running"
    job.locked_at = datetime.now(timezone.utc)
    job.locked_by = worker_id
    job.attempts += 1
    job.updated_at = datetime.now(timezone.utc)
    jid = job.id
    session.commit()
    return jid


def reclaim_stale(session: Session, minutes: int = 15) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    result = session.execute(
        update(Job)
        .where(Job.status == "running", Job.locked_at < cutoff)
        .values(status="queued", locked_at=None, locked_by=None, updated_at=datetime.now(timezone.utc))
    )
    session.commit()
    return result.rowcount or 0


def finish(session: Session, job: Job, result: dict | None = None) -> None:
    job.status = "done"
    job.result = result
    job.locked_at = None
    job.error = None
    job.updated_at = datetime.now(timezone.utc)
    session.commit()


def fail(session: Session, job: Job, exc: Exception) -> None:
    job.error = f"{type(exc).__name__}: {exc}"
    job.updated_at = datetime.now(timezone.utc)
    job.locked_at = None
    if job.attempts < job.max_attempts:
        job.status = "queued"
        job.run_after = datetime.now(timezone.utc) + timedelta(seconds=5 * job.attempts)
    else:
        job.status = "failed"
    session.commit()
