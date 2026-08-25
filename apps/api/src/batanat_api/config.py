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


def _repo_root() -> Path:
    """Where to look for `.env`, in a way that survives being installed.

    In the repo this file is `apps/api/src/batanat_api/config.py`, so the root
    is four levels up. In the image it is `/app/src/batanat_api/config.py` —
    two levels shallower — and a hardcoded `parents[4]` raised IndexError at
    *import* time, so every container died before it could log a reason.

    Walk up looking for a marker instead, and fall back to the highest real
    parent. `.env` is a local development convenience; a container gets its
    configuration from the environment, so not finding one is not an error.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".env").is_file() or (parent / ".git").exists():
            return parent
    return here.parents[-1]


REPO_ROOT = _repo_root()


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

    # `lax` when the UI and API share a site. Two ngrok subdomains do not
    # (ngrok-free.app is on the Public Suffix List), and a Lax cookie is never
    # sent cross-site — login 200s, then /api/auth/me 401s forever. Use `none`
    # there; `cookie_kwargs` forces Secure on to match.
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # The seeded account's password. Convenient in development, and refused
    # outright outside it — see `assert_safe_for_environment`.
    default_user_email: str = "martin@batanat.com"
    default_user_password: str = "batanat-dev"

    def assert_safe_for_environment(self) -> None:
        """Refuse to run with development defaults anywhere but local.

        A default password that ships is not a default, it is a backdoor. This
        turns "we meant to change that" into a failed boot.
        """
        if self.app_env == "local":
            return

        problems: list[str] = []
        if self.default_user_password == "batanat-dev":
            problems.append(
                "DEFAULT_USER_PASSWORD is still the development default. Set a real one."
            )
        if not self.session_secret:
            problems.append("SESSION_SECRET is not set.")
        if not self.token_encryption_key:
            problems.append("TOKEN_ENCRYPTION_KEY is not set.")

        if problems:
            raise RuntimeError(
                f"Refusing to start with APP_ENV={self.app_env}: " + " ".join(problems)
            )

    # --- providers (phase 2) ---
    #
    # The redirect URIs are derived from `api_public_url` rather than configured
    # separately — they are always `<api>/api/connections/<provider>/callback`,
    # and restating that is how one gets changed and the other does not. Moving
    # the API to a new tunnel is now a single edit.
    #
    # Set the env var to override, for the case where the provider must be sent
    # somewhere the API does not otherwise know about (a proxy, a vanity host).
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None

    zoho_client_id: str | None = None
    zoho_client_secret: str | None = None
    zoho_redirect_uri: str | None = None
    zoho_accounts_url: str = "https://accounts.zoho.com"

    def redirect_uri_for(self, provider: str) -> str:
        """Where the provider sends the browser back after authorisation.

        `provider` is the path segment the callback route matches, which is the
        provider enum's value — `gmail`, `zoho`.
        """
        override = {
            "gmail": self.google_redirect_uri,
            "zoho": self.zoho_redirect_uri,
        }.get(provider)
        if override:
            return override
        return f"{self.api_public_url.rstrip('/')}/api/connections/{provider}/callback"

    whatsapp_phone_number_id: str | None = None
    whatsapp_business_number: str | None = None
    whatsapp_access_token: str | None = None
    whatsapp_app_secret: str | None = None
    whatsapp_verify_token: str | None = None

    # --- model + search providers (phase 3, 4) ---
    # Which provider the agent calls. Groq and OpenRouter are OpenAI-compatible
    # and share one client; swapping is an env change, no code knows the
    # difference. Leave `agent_model` blank to take the provider's default.
    llm_provider: Literal["anthropic", "groq", "openrouter"] = "groq"
    agent_model: str = ""

    anthropic_api_key: str | None = None
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None

    tavily_api_key: str | None = None

    # --- agent limits (phase 3) ---
    agent_max_iterations: int = 12
    agent_token_budget: int = 120_000
    agent_wall_clock_timeout_s: float = 180.0
    tool_circuit_breaker_threshold: int = 3
    tool_circuit_breaker_cooldown_s: int = 900

    # --- report delivery (phase 6) ---
    # Sender only. Recipients live on the user row, set in Settings → Report
    # recipients; see notifications/email_sender.py.
    sendgrid_api_key: str | None = None
    report_from_email: str | None = None
    report_from_name: str = "Batanat Harness"
    report_reply_to: str | None = None

    # --- scheduling (phase 5) ---
    scheduler_timezone: str = "Africa/Nairobi"
    tender_cron_daily: str = "0 11,17,20 * * *"
    # Weekday *names*, not numbers. APScheduler counts day-of-week from Monday=0
    # while crontab counts from Sunday=0, and `from_crontab` does not remap — so
    # "0 8 * * 1" silently means Tuesday here. Names mean the same in both.
    tender_cron_weekly: str = "0 8 * * mon"
    maintenance_cron: str = "0 2 * * *"
    # Off by default so tests and one-off scripts never start cron jobs.
    enable_scheduler: bool = False

    # --- gmail push (phase 5) ---
    gmail_pubsub_topic: str | None = None
    gmail_pubsub_audience: str | None = None
    gmail_pubsub_service_account: str | None = None

    # --- memory (phase 8) ---
    embeddings_provider: str = "fastembed"
    embeddings_model: str = "BAAI/bge-small-en-v1.5"

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
