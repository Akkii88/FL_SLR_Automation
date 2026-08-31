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

    # --- LLM Primary Provider (Groq) ---
    llm_provider: str = Field(default="", description="Primary LLM provider (groq, gemini)")
    llm_api_key: str = Field(default="", description="Primary LLM API key")
    llm_model: str = Field(default="", description="Primary LLM model")

    # --- Groq-specific Retry / Rate Limiting ---
    groq_max_retries: int = Field(default=5, description="Max retry attempts for Groq")
    groq_initial_backoff_seconds: float = Field(default=2.0, description="Initial backoff for Groq")
    groq_max_backoff_seconds: float = Field(default=60.0, description="Max backoff cap for Groq")
    groq_request_delay_seconds: float = Field(default=0.5, description="Delay between Groq requests")

    # --- Gemini Fallback Provider ---
    gemini_api_key: str = Field(default="", description="Google Gemini API key")
    gemini_model: str = Field(default="gemini-3.6-flash", description="Gemini model name")
    gemini_project_name: str = Field(default="", description="Gemini project name")
    gemini_project_number: str = Field(default="", description="Gemini project number")

    # --- Gemini-specific Retry / Rate Limiting ---
    gemini_max_retries: int = Field(default=3, description="Max retry attempts for Gemini")
    gemini_initial_backoff_seconds: float = Field(default=1.0, description="Initial backoff for Gemini")
    gemini_max_backoff_seconds: float = Field(default=30.0, description="Max backoff cap for Gemini")
    gemini_request_delay_seconds: float = Field(default=0.3, description="Delay between Gemini requests")

    # --- OpenRouter Fallback Provider (3rd) ---
    openrouter_enabled: bool = Field(default=False, description="Whether OpenRouter is enabled (disabled if model unavailable)")
    openrouter_api_key: str = Field(default="", description="OpenRouter API key")
    openrouter_model: str = Field(default="openai/gpt-oss-120b:free", description="OpenRouter model")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", description="OpenRouter base URL")

    # --- OpenRouter-specific Retry / Rate Limiting ---
    openrouter_max_retries: int = Field(default=3, description="Max retry attempts for OpenRouter")
    openrouter_initial_backoff_seconds: float = Field(default=2.0, description="Initial backoff for OpenRouter")
    openrouter_max_backoff_seconds: float = Field(default=30.0, description="Max backoff cap for OpenRouter")
    openrouter_request_delay_seconds: float = Field(default=1.0, description="Delay between OpenRouter requests")

    # --- Legacy LLM settings (kept for backward compatibility) ---
    llm_max_retries: int = Field(default=5, description="Legacy: Max retry attempts")
    llm_initial_backoff_seconds: float = Field(default=2.0, description="Legacy: Initial backoff")
    llm_max_backoff_seconds: float = Field(default=60.0, description="Legacy: Max backoff cap")
    llm_request_delay_seconds: float = Field(default=0.5, description="Legacy: Delay between requests")

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
