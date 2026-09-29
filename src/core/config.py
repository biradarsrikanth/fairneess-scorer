from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, read from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr = Field(validation_alias="AZURE_DB_URL")
    # Shared secret the gateway sends in X-API-Key
    api_key: SecretStr = Field(validation_alias="SCORER_API_KEY", min_length=32)
    # Timestamps are stored in UTC; scoring buckets (night, weekend) use the team's local time
    team_timezone: str = "Asia/Kolkata"
    cache_ttl_seconds: int = Field(default=60, ge=0)
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "text"

    @field_validator("team_timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone '{value}'") from exc
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.team_timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
