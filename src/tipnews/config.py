from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TIPNEWS_", env_file=None, extra="ignore")

    token_file: Path = Path("secrets/telegram_token")
    database_url: str = "sqlite+aiosqlite:///data/tipnews.db"
    sources_file: Path = Path("config/sources.toml")
    timezone: str = "Europe/Moscow"
    digest_time: time = time(7, 15)
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:0.6b"
    weather_enabled: bool = True
    collect_interval_seconds: int = Field(default=1800, ge=60)
    feed_max_bytes: int = Field(default=4 * 1024 * 1024, ge=1024, le=8 * 1024 * 1024)
    retention_days: int = Field(default=30, ge=7)
    heartbeat_file: Path = Path("data/heartbeat")

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("digest_time")
    @classmethod
    def naive_time(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("Use a local HH:MM time and the timezone setting")
        return value
