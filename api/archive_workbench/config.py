"""Runtime configuration. Keys come from the environment or a .env file."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# api/archive_workbench/config.py -> repository root
ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://archive:archive@localhost:5432/archive"
    data_dir: Path = ROOT / "data"

    llm_api_key: str = ""
    anthropic_api_key: str = ""
    llm_model: str = "anthropic/claude-sonnet-4-5"
    llm_api_base: str = ""
    llm_model_tier1: str = ""
    llm_model_tier2: str = ""
    llm_model_tier3: str = ""

    ocr_engine: str = "tesseract"
    tesseract_langs: str = "eng+kan+mar+hin"

    embedding_provider: str = "local"  # local | api | hash
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dim: int = 384

    europeana_api_key: str = ""
    dpla_api_key: str = ""
    app_password: str = ""

    auth_disabled: bool = True
    google_client_id: str = ""
    google_client_secret: str = ""
    auth_secret: str = ""
    app_base_url: str = "http://localhost:3000"
    allowed_emails: str = ""
    allowed_domains: str = ""
    admin_emails: str = "praveenmaths89@gmail.com"

    historical_bias: bool = True
    escalation_threshold: float = 0.85
    render_dpi: int = 200
    api_image_max_edge: int = 2000
    max_files_per_job: int = 50
    max_file_mb: int = 500
    max_pages_per_file: int = 500
    library_cache_hours: int = 24

    @property
    def model_key(self) -> str:
        return self.llm_api_key or self.anthropic_api_key

    def model_for_tier(self, tier: int) -> str:
        specific = {1: self.llm_model_tier1, 2: self.llm_model_tier2, 3: self.llm_model_tier3}[tier]
        return specific or self.llm_model


settings = Settings()
