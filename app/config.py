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
    max_files_per_job: int = 50
    max_file_mb: int = 100
    max_pages_per_file: int = 500
    workers: int = 2

    def model_for_tier(self, tier: int) -> str:
        return {1: self.model_tier1, 2: self.model_tier2, 3: self.model_tier3}[tier]


settings = Settings()
