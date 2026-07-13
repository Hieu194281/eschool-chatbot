"""Centralized configuration (pydantic-settings).

Single validated `Settings` singleton imported by every module (DRY). Secrets
come ONLY from the environment / .env — never inlined. Required secrets fail
fast at startup with an explicit error naming the missing key.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Flat schema (KISS — <25 keys, no premature grouping).
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Channel (Messenger) ──────────────────────────────────
    page_access_token: str = ""
    app_secret: str = ""
    verify_token: str = ""
    messenger_api_version: str = "v21.0"

    # ── Gemini ───────────────────────────────────────────────
    google_api_key: str = ""
    gemini_model_main: str = "gemini-2.5-flash"
    gemini_model_lite: str = "gemini-2.5-flash-lite"
    gemini_embed_model: str = "gemini-embedding-001"

    # ── Google Sheet KB + leads ──────────────────────────────
    google_sa_json_path: str = ""
    kb_sheet_id: str = ""
    leads_sheet_id: str = ""
    kb_sync_interval_sec: int = 300

    # ── Postgres ─────────────────────────────────────────────
    postgres_dsn: str = "postgresql://tuyensinh:tuyensinh@localhost:5432/tuyensinh"

    # ── Telegram ─────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_webhook_secret: str = ""

    # ── Rate limit / spend caps ──────────────────────────────
    rate_limit_per_min: int = 10
    rate_limit_per_day: int = 200
    max_concurrent_invokes: int = 20
    gemini_daily_budget: int = 10000

    # ── PII retention (PDPD Decree 13/2023) ──────────────────
    pii_retention_days: int = 180

    # ── App behavior ─────────────────────────────────────────
    debounce_seconds: float = 6.0
    shadow_mode: bool = True
    handoff_auto_resume_hours: int = 24
    log_level: str = "INFO"

    # ── LangGraph hardening ──────────────────────────────────
    langgraph_strict_msgpack: bool = True

    # Secrets required for the service to actually serve real traffic.
    # (Kept minimal so unit tests can construct Settings without live creds.)
    _REQUIRED_FOR_SERVE = (
        "page_access_token",
        "app_secret",
        "verify_token",
        "google_api_key",
        "postgres_dsn",
    )

    def require_serve_secrets(self) -> None:
        """Fail fast (called from lifespan) if a serve-critical secret is blank."""
        missing = [k for k in self._REQUIRED_FOR_SERVE if not getattr(self, k)]
        if missing:
            raise RuntimeError(
                "Missing required environment variables: "
                + ", ".join(m.upper() for m in missing)
                + " — set them in .env (see .env.example)."
            )


@lru_cache
def get_settings() -> Settings:
    """Cached singleton. Import this everywhere; never re-read env directly."""
    return Settings()
