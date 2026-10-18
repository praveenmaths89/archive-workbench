"""Shared fixtures. Hash embeddings so tests do not download a model."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://archive:archive@localhost:5432/archive",
)
os.environ["DATA_DIR"] = "/tmp/aw-test-data"
Path("/tmp/aw-test-data").mkdir(parents=True, exist_ok=True)

import pytest
from sqlalchemy import text

from archive_workbench.config import settings
from archive_workbench.db import engine
from archive_workbench.migrate import run_migrations

settings.embedding_provider = "hash"
settings.data_dir = Path("/tmp/aw-test-data")
settings.ocr_engine = "tesseract"
settings.llm_api_key = ""
settings.anthropic_api_key = ""
settings.app_password = ""


def database_up() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def migrated():
    if not database_up():
        pytest.skip("Postgres is not running")
    run_migrations()
    return True


@pytest.fixture
def db(migrated):
    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE rate_hits, library_cache, messages, notes, jobs, chunks, regions, pages, documents "
            "RESTART IDENTITY CASCADE"
        ))
    yield
