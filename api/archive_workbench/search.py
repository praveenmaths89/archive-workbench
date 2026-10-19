"""Hybrid retrieval: full-text rank plus pgvector cosine similarity, equal weight."""
from __future__ import annotations

import html
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .embeddings import get_embedder
from .models import Chunk, Document, Note, Page


def _fts(session: Session, query: str, document_id: uuid.UUID | None, maker):
    tsq = maker(query)
    rank = func.ts_rank_cd(Chunk.tsv, tsq)
    stmt = select(Chunk, rank.label("rank")).where(Chunk.tsv.bool_op("@@")(tsq))
    if document_id is not None:
        stmt = stmt.where(Chunk.document_id == document_id)
    stmt = stmt.order_by(rank.desc()).limit(30)
    return session.execute(stmt).all()


def _scale(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def hybrid_search(session: Session, query: str, document_id: uuid.UUID | None = None, k: int = 6) -> list[Chunk]:
    query = (query or "").strip()
    if not query:
        return []
    qvec = get_embedder().embed_query(query)

    fts_rows = []
    for maker in (lambda q: func.websearch_to_tsquery("simple", q), lambda q: func.plainto_tsquery("simple", q)):
        try:
            fts_rows = _fts(session, query, document_id, maker)
            break
        except Exception:
            session.rollback()
            fts_rows = []

    vec_rank = 1 - Chunk.embedding.cosine_distance(qvec)
    vec_stmt = (
        select(Chunk, vec_rank.label("rank"))
        .where(Chunk.embedding.is_not(None))
    )
    if document_id is not None:
        vec_stmt = vec_stmt.where(Chunk.document_id == document_id)
    vec_stmt = vec_stmt.order_by(Chunk.embedding.cosine_distance(qvec)).limit(30)
    try:
        vec_rows = session.execute(vec_stmt).all()
    except Exception:
        session.rollback()
        vec_rows = []

    combined: dict[uuid.UUID, dict] = {}
    fts_scaled = _scale([float(row.rank or 0) for row in fts_rows])
    vec_scaled = _scale([float(row.rank or 0) for row in vec_rows])
    for row, score in zip(fts_rows, fts_scaled):
        combined[row.Chunk.id] = {"chunk": row.Chunk, "fts": score, "vec": 0.0}
    for row, score in zip(vec_rows, vec_scaled):
        slot = combined.setdefault(row.Chunk.id, {"chunk": row.Chunk, "fts": 0.0, "vec": 0.0})
        slot["vec"] = score
    ranked = sorted(combined.values(), key=lambda item: item["fts"] + item["vec"], reverse=True)
    return [item["chunk"] for item in ranked[:k]]


def _snippet(text: str, query: str) -> str:
    words = [word for word in re.split(r"\s+", query or "") if word]
    plain = " ".join((text or "").split())
    if not words:
        return html.escape(plain[:180])
    pattern = re.compile("|".join(re.escape(word) for word in words), re.I)
    match = pattern.search(plain)
    if match is None:
        return html.escape(plain[:180])
    start = max(0, match.start() - 60)
    end = min(len(plain), match.end() + 100)
    piece = plain[start:end]
    parts: list[str] = []
    last = 0
    for found in pattern.finditer(piece):
        parts.append(html.escape(piece[last:found.start()]))
        parts.append("<mark>" + html.escape(found.group(0)) + "</mark>")
        last = found.end()
    parts.append(html.escape(piece[last:]))
    return "".join(parts)


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def matching_document_ids(
    session: Session,
    document_id: uuid.UUID | None,
    collection: str | None,
    language: str | None,
    engine: str | None,
    uploaded_from: date | None,
    uploaded_to: date | None,
) -> set[uuid.UUID] | None:
    active = any([document_id, collection, language, engine, uploaded_from, uploaded_to])
    if not active:
        return None
    stmt = select(Document.id)
    if document_id is not None:
        stmt = stmt.where(Document.id == document_id)
    if collection:
        stmt = stmt.where(func.lower(Document.collection) == collection.strip().lower())
    if language:
        stmt = stmt.where(Document.language == language)
    if uploaded_from is not None:
        stmt = stmt.where(Document.created_at >= _day_start(uploaded_from))
    if uploaded_to is not None:
        stmt = stmt.where(Document.created_at < _day_start(uploaded_to) + timedelta(days=1))
    if engine:
        stmt = stmt.where(Document.id.in_(select(Page.document_id).where(Page.ocr_engine == engine)))
    return set(session.scalars(stmt).all())


def workspace_search(
    session: Session,
    query: str,
    document_id: uuid.UUID | None = None,
    collection: str | None = None,
    language: str | None = None,
    engine: str | None = None,
    uploaded_from: date | None = None,
    uploaded_to: date | None = None,
    k: int = 20,
) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    allowed = matching_document_ids(
        session, document_id, collection, language, engine, uploaded_from, uploaded_to,
    )
    if allowed is not None and not allowed:
        return []
    hits: list[dict] = []
    docs = {
        doc.id: doc
        for doc in session.scalars(select(Document)).all()
        if allowed is None or doc.id in allowed
    }
    for chunk in hybrid_search(session, query, document_id, k=30):
        if allowed is not None and chunk.document_id not in allowed:
            continue
        doc = docs.get(chunk.document_id)
        if doc is None:
            continue
        hits.append({
            "kind": "transcription",
            "document_id": str(chunk.document_id),
            "filename": doc.filename,
            "title": doc.title or doc.filename,
            "collection": doc.collection,
            "language": doc.language,
            "page": chunk.page_number,
            "region_id": str(chunk.region_id) if chunk.region_id else None,
            "snippet": _snippet(chunk.text, query),
            "text": chunk.text,
        })
        if len(hits) >= k:
            break
    if len(hits) < k:
        tsq = func.plainto_tsquery("simple", query)
        trans = func.to_tsvector("simple", func.coalesce(Page.translation, ""))
        stmt = (
            select(Page)
            .where(Page.translation.is_not(None))
            .where(trans.bool_op("@@")(tsq))
        )
        if allowed is not None:
            stmt = stmt.where(Page.document_id.in_(allowed))
        try:
            pages = session.scalars(stmt.limit(10)).all()
        except Exception:
            session.rollback()
            pages = []
        for page in pages:
            doc = docs.get(page.document_id)
            if doc is None:
                continue
            hits.append({
                "kind": "translation",
                "document_id": str(page.document_id),
                "filename": doc.filename,
                "title": doc.title or doc.filename,
                "collection": doc.collection,
                "language": page.translation_language or doc.language,
                "page": page.number,
                "region_id": None,
                "snippet": _snippet(page.translation or "", query),
                "text": page.translation or "",
            })
    if len(hits) < k:
        tsq = func.plainto_tsquery("simple", query)
        note_vec = func.to_tsvector("simple", func.coalesce(Note.body, ""))
        stmt = select(Note).where(note_vec.bool_op("@@")(tsq))
        if allowed is not None:
            stmt = stmt.where(Note.document_id.in_(allowed))
        try:
            notes = session.scalars(stmt.limit(10)).all()
        except Exception:
            session.rollback()
            notes = []
        for note in notes:
            doc = docs.get(note.document_id)
            if doc is None:
                continue
            hits.append({
                "kind": "note",
                "document_id": str(note.document_id),
                "filename": doc.filename,
                "title": doc.title or doc.filename,
                "collection": doc.collection,
                "language": doc.language,
                "page": None,
                "region_id": None,
                "snippet": _snippet(note.body, query),
                "text": note.body,
            })
    return hits[:k]
