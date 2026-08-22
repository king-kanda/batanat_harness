"""Application settings.

Everything the app needs comes from the environment. `.env` at the repo root is
loaded for local development; in Docker the values come from the environment
directly. `.env.example` documents every variable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- runtime ---
    app_env: Literal["local", "staging", "production"] = "local"
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_public_url: str = "http://localhost:8000"
    web_public_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000"

    # --- datastores ---
    # Defaults target locally installed services on standard ports; see .env.example.
    database_url: str = "postgresql://postgres:password@localhost:5432/batanat"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    mongo_url: str = "mongodb://localhost:27017/"
    mongo_db: str = "batanat_raw"
    redis_url: str = "redis://localhost:6379/0"

    # --- security ---
    # Fernet master key for the token vault. Absent means credentials cannot be
    # stored; the app still boots so the UI can say so.
    token_encryption_key: str | None = None
    session_secret: str | None = None

    # --- providers (phase 2) ---
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/api/connections/gmail/callback"

    zoho_client_id: str | None = None
    zoho_client_secret: str | None = None
    zoho_redirect_uri: str = "http://localhost:8000/api/connections/zoho/callback"
    zoho_accounts_url: str = "https://accounts.zoho.com"

    whatsapp_phone_number_id: str | None = None
    whatsapp_business_number: str | None = None
    whatsapp_access_token: str | None = None
    whatsapp_app_secret: str | None = None
    whatsapp_verify_token: str | None = None

    # --- operational guards (enforced from phase 3 onward) ---
    kill_switch: bool = False
    crm_dry_run: bool = True
    demo_mode: bool = False

    # How long a single health probe may take before it is reported as down.
    health_check_timeout_s: float = 2.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_local(self) -> bool:
        return self.app_env == "local"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
