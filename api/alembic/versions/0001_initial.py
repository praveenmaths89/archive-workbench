"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-10-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("title", sa.String(500), nullable=False, server_default=""),
        sa.Column("kind", sa.String(40), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(40), nullable=False, server_default="queued"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("language", sa.String(40), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("stop_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="skipped"),
        sa.Column("image_path", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("translation", sa.Text(), nullable=True),
        sa.Column("translation_language", sa.String(40), nullable=True),
        sa.Column("ocr_engine", sa.String(40), nullable=True),
        sa.Column("language", sa.String(40), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("uncertain", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("original_regions", postgresql.JSONB(), nullable=True),
        sa.Column("tsv", postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple', coalesce(text, ''))", persisted=True)),
    )
    op.create_index("pages_document_idx", "pages", ["document_id"])
    op.create_index("pages_tsv_idx", "pages", ["tsv"], postgresql_using="gin")
    op.create_table(
        "regions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("type", sa.String(40), nullable=False, server_default="line"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("x", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("y", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("w", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("h", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_index("regions_document_idx", "regions", ["document_id"])
    op.create_index("regions_page_idx", "regions", ["page_id"])
    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pages.id", ondelete="CASCADE"), nullable=True),
        sa.Column("region_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("regions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("tsv", postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple', coalesce(text, ''))", persisted=True)),
    )
    op.create_index("chunks_document_idx", "chunks", ["document_id"])
    op.create_index("chunks_tsv_idx", "chunks", ["tsv"], postgresql_using="gin")
    op.create_index(
        "chunks_embedding_idx",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("notes_document_idx", "notes", ["document_id"])
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("citations", postgresql.JSONB(), nullable=True),
        sa.Column("dropped", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("messages_document_idx", "messages", ["document_id"])
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("run_after", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(120), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("jobs_document_idx", "jobs", ["document_id"])
    op.create_index("jobs_queue_idx", "jobs", ["status", "run_after", "created_at"])
    op.create_table(
        "library_cache",
        sa.Column("connector", sa.String(80), primary_key=True),
        sa.Column("query", sa.String(1000), primary_key=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "rate_hits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("bucket", sa.String(80), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("rate_hits_bucket_idx", "rate_hits", ["bucket"])


def downgrade() -> None:
    op.drop_table("rate_hits")
    op.drop_table("library_cache")
    op.drop_table("jobs")
    op.drop_table("messages")
    op.drop_table("notes")
    op.drop_table("chunks")
    op.drop_table("regions")
    op.drop_table("pages")
    op.drop_table("documents")
