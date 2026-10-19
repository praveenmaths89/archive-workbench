"""Shared hit shape, cache, and rate limit."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import settings
from ..models import LibraryCache

UA = "ArchiveWorkbench/1.0 (mailto:praveenmaths89@gmail.com)"


@dataclass
class Hit:
    source: str
    title: str
    url: str
    creators: list[str] = field(default_factory=list)
    date: str | None = None
    description: str = ""


@dataclass
class SourceResult:
    source: str
    status: str  # ok | error | not_configured
    hits: list[Hit] = field(default_factory=list)
    error: str | None = None

    def to_json(self) -> dict:
        return {
            "source": self.source,
            "status": self.status,
            "error": self.error,
            "hits": [asdict(h) for h in self.hits],
        }


def _short_error(exc: Exception) -> str:
    import httpx
    if isinstance(exc, httpx.TimeoutException):
        return "timed out"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return text[:180]


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]


def first_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(v) for v in value if v)[:1000]
    return str(value)[:1000]


def acquire(session: Session, bucket: str, per_minute: int, max_wait: float = 3.0) -> bool:
    """Shared limiter so the API and the worker together stay under the cap."""
    deadline = time.monotonic() + max_wait
    while True:
        session.execute(
            text("DELETE FROM rate_hits WHERE bucket = :bucket AND at < now() - interval '60 seconds'"),
            {"bucket": bucket},
        )
        count = session.execute(
            text("SELECT count(*) FROM rate_hits WHERE bucket = :bucket"),
            {"bucket": bucket},
        ).scalar() or 0
        if count < per_minute:
            session.execute(text("INSERT INTO rate_hits (bucket) VALUES (:bucket)"), {"bucket": bucket})
            session.commit()
            return True
        session.rollback()
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def cached(session: Session, connector: str, query: str) -> dict | None:
    row = session.get(LibraryCache, {"connector": connector, "query": query})
    if row is None:
        return None
    age = datetime.now(timezone.utc) - row.fetched_at
    if age > timedelta(hours=settings.library_cache_hours):
        return None
    return row.payload


def store_cache(session: Session, connector: str, query: str, payload: dict) -> None:
    stmt = pg_insert(LibraryCache).values(
        connector=connector, query=query[:1000], payload=payload, fetched_at=datetime.now(timezone.utc)
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["connector", "query"],
        set_={"payload": payload, "fetched_at": datetime.now(timezone.utc)},
    )
    session.execute(stmt)
    session.commit()


def search_libraries(session: Session, query: str, sources: list[str], limit: int = 8) -> list[SourceResult]:
    from . import CONNECTORS

    query = " ".join(query.split())[:500]
    results: list[SourceResult] = []
    for name in sources:
        connector = CONNECTORS.get(name)
        if connector is None:
            results.append(SourceResult(name, "error", error=f"unknown source {name}"))
            continue
        if not connector.configured():
            results.append(SourceResult(name, "not_configured"))
            continue
        hit = cached(session, name, query)
        if hit is not None:
            results.append(SourceResult(
                source=name,
                status=hit.get("status", "ok"),
                error=hit.get("error"),
                hits=[Hit(**h) for h in hit.get("hits", [])],
            ))
            continue
        if not acquire(session, connector.bucket, connector.per_minute):
            results.append(SourceResult(name, "error", error="rate limit reached; try again in a minute"))
            continue
        try:
            found = connector.search(query, limit)
            result = SourceResult(name, "ok", found)
            store_cache(session, name, query, result.to_json())
        except Exception as exc:
            result = SourceResult(name, "error", error=_short_error(exc))
        results.append(result)
    return results
