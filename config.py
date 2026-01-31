"""config.py - Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """Settings loaded from .env file or environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    firecrawl_api_key: str
    anthropic_api_key: str
    database_url: str  # Required: postgresql://user:pass@host:port/db

    # Google OAuth
    google_client_id: str
    google_client_secret: str

    # Microsoft OAuth (for MSP customers using Azure/M365)
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""

    # Session secret (generate with: openssl rand -hex 32)
    session_secret: str = "dev-secret-change-in-production"

    # Separate JWT secret (falls back to session_secret when empty)
    jwt_secret: str = ""

    # App URL (for OAuth redirect)
    app_url: str = "http://localhost:8000"

    # Stripe
    stripe_secret_key: str
    stripe_webhook_secret: str = ""

    # SerpAPI (for Google News)
    serp_api_key: str = ""

    # OpenAI (for embeddings in v2 materials feature)
    openai_api_key: str = ""

    # Cloudflare R2 (for materials file storage in v2)
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "auggie-materials"

    # Apollo.io (for contact enrichment) - requires paid plan
    apollo_api_key: str = ""

    # People Data Labs (for contact enrichment)
    pdl_api_key: str = ""

    # LeadMagic (for contact enrichment)
    leadmagic_api_key: str = ""

    # HubSpot (CRM integration)
    hubspot_client_id: str = ""
    hubspot_client_secret: str = ""

    # Salesforce (CRM integration)
    salesforce_client_id: str = ""
    salesforce_client_secret: str = ""

    # Outreach (sales engagement)
    outreach_client_id: str = ""
    outreach_client_secret: str = ""

    # SalesLoft (sales engagement)
    salesloft_client_id: str = ""
    salesloft_client_secret: str = ""

    # SEC EDGAR (free, no key needed)
    edgar_enabled: bool = True

    # Federal Register API (free, no key needed)
    federal_register_enabled: bool = True

    # Database pool sizing
    db_pool_min: int = 5
    db_pool_max: int = 20
    db_pool_acquire_timeout: int = 10
    db_statement_timeout: int = 30

    # Slack webhook for internal failure alerts (task exhausted retries)
    slack_webhook_url: str = ""

    # Feature flags
    materials_enabled: bool = False

    # In-process worker
    worker_enabled: bool = True
    worker_concurrency: int = 10
    worker_poll_interval: int = 2

    @property
    def r2_endpoint_url(self) -> str:
        """Get the R2 S3-compatible endpoint URL."""
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"



@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
