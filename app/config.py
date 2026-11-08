from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    anthropic_api_key: str = ""
    # Tier -> Claude model id. Configuration, not code: update as models change.
    model_tier1: str = "claude-haiku-5-5"
    model_tier2: str = "claude-sonnet-5-5"
    model_tier3: str = "claude-opus-5-5"
    model_research: str = "claude-opus-5-5"

    data_dir: Path = ROOT / "data"
    use_mock: bool = False  # force the mock adapter (tests / no key)
    historical_bias: bool = True  # scans without a text layer start at tier 3
    escalation_threshold: float = 0.85
    render_dpi: int = 200
    api_image_max_edge: int = 2000
    max_render_edge: int = 4500  # cap a hostile page's pixmap
    max_files_per_job: int = 50
    max_file_mb: int = 100
    max_pages_per_file: int = 500
    workers: int = 2

    # PUBLIC_MODE: local Tesseract only. Hosted Render mode is separate and keeps Claude.
    public_mode: bool = False
    # Shared server for the full OCR and web-search app. Uses ANTHROPIC_API_KEY for every
    # visitor. Sessions are isolated. This is not a spending cap.
    hosted_mode: bool = False
    session_secret: str = ""
    cookie_secure: bool = False
    ocr_engine: str = "auto"  # auto | tesseract | claude | mock
    public_max_files: int = 3
    public_max_file_mb: int = 8
    public_max_pages: int = 5
    public_max_jobs: int = 8
    public_max_jobs_per_hour: int = 6
    public_max_pages_per_day: int = 20
    public_retention_hours: int = 24

    def model_for_tier(self, tier: int) -> str:
        return {1: self.model_tier1, 2: self.model_tier2, 3: self.model_tier3}[tier]

    @property
    def shared(self) -> bool:
        """Visitor isolation and technical quotas. Personal mode leaves this false."""
        return self.public_mode or self.hosted_mode

    @property
    def uses_local_ocr(self) -> bool:
        engine = self.ocr_engine.lower()
        if engine == "tesseract":
            return True
        if engine in ("claude", "mock"):
            return False
        return self.public_mode and not self.use_mock

    @property
    def file_limit_mb(self) -> int:
        return self.public_max_file_mb if self.shared else self.max_file_mb

    @property
    def files_limit(self) -> int:
        return self.public_max_files if self.shared else self.max_files_per_job

    @property
    def pages_limit(self) -> int:
        return self.public_max_pages if self.shared else self.max_pages_per_file


settings = Settings()
