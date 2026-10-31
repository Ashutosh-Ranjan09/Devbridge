"""Settings, from the environment and `.env`, prefix CHAT_."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]          # chat/


class Settings(BaseSettings):
    # The module's own .env, wherever the command is run from, as assessment does.
    model_config = SettingsConfigDict(env_prefix="CHAT_", env_file=ROOT / ".env", extra="ignore")

    # Bearer key for `chat serve`. Unset: one is generated and printed at startup.
    api_key: str | None = None
    # 32 bytes, base64. Required: a key made up at startup would be lost at the next one,
    # and every message sealed with it.
    encryption_key: str | None = None

    max_body_chars: int = 4000
    # Messages one person may send in a minute, across all their threads.
    per_minute: int = 30
    # An idle stream sends a comment this often, so nothing between closes it.
    keepalive_seconds: float = 15.0

    db_path: Path = ROOT / ".data" / "chat.db"


settings = Settings()
