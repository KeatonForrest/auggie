"""config.py - Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Settings loaded from .env file or environment variables."""

    firecrawl_api_key: str
    anthropic_api_key: str
    database_url: str  # Required: postgresql://user:pass@host:port/db

    # Google OAuth
    google_client_id: str
    google_client_secret: str

    # Session secret (generate with: openssl rand -hex 32)
    session_secret: str = "dev-secret-change-in-production"

    # App URL (for OAuth redirect)
    app_url: str = "http://localhost:8000"

    # Stripe
    stripe_secret_key: str
    stripe_webhook_secret: str = ""

    # SerpAPI (for Google News)
    serp_api_key: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
