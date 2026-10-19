"""Settings, allowlist, sessions, and document search fields.

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("collection", sa.String(200), nullable=True))
    op.add_column("documents", sa.Column("ocr_engine", sa.String(40), nullable=True))
    op.add_column("documents", sa.Column("progress", sa.Text(), nullable=True))
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
    )
    op.create_table(
        "access_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("value", sa.String(320), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(20), nullable=False, server_default="local"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("kind", "value", name="access_kind_value"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("sessions_token_hash_idx", "sessions", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("sessions_token_hash_idx", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("access_entries")
    op.drop_table("app_settings")
    op.drop_column("documents", "progress")
    op.drop_column("documents", "ocr_engine")
    op.drop_column("documents", "collection")
