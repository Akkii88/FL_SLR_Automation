"""
FL-SLR Configuration Management
================================
Loads application settings from environment variables and .env file.
Uses pydantic-settings for validation.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # --- OpenAlex ---
    openalex_api_key: str = Field(default="", description="OpenAlex API key (optional)")
    openalex_email: str = Field(default="", description="Email for OpenAlex polite pool")

    # --- Database ---
    database_url: str = Field(
        default="sqlite:///data/fl_slr.db",
        description="SQLAlchemy database URL"
    )

    # --- Application ---
    app_env: str = Field(default="development")
    app_host: str = Field(default="127.0.0.1")
    app_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")

    # --- Search Defaults ---
    default_max_candidates: int = Field(default=500)

    # --- LLM (future) ---
    llm_provider: str = Field(default="")
    llm_api_key: str = Field(default="")
    llm_model: str = Field(default="")

    # --- LLM Retry / Rate Limiting ---
    llm_max_retries: int = Field(default=5, description="Max retry attempts for rate-limited LLM requests")
    llm_initial_backoff_seconds: float = Field(default=2.0, description="Initial backoff seconds for retries")
    llm_max_backoff_seconds: float = Field(default=60.0, description="Maximum backoff seconds (cap)")
    llm_request_delay_seconds: float = Field(default=0.5, description="Delay between consecutive LLM requests to pace TPM")

    # --- Project Root ---
    project_root: Path = Field(
        default=Path(__file__).resolve().parent.parent.parent
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Singleton settings instance
settings = Settings()
