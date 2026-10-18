"""Hybrid retrieval: full-text rank plus pgvector cosine similarity, equal weight."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .embeddings import get_embedder
from .models import Chunk


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
