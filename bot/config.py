"""Application settings loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    portal_url: str = "http://localhost:8000"
    portal_user: str = "demo"
    portal_password: SecretStr = SecretStr("demo1234")

    db_path: str = "data/gruas.db"
    poll_interval_seconds: int = 4
    headless: bool = True
    # "" = Chromium de Playwright; "msedge" o "chrome" = navegador ya instalado en el sistema
    browser_channel: str = ""

    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
