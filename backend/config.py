from functools import lru_cache

from pydantic import Field, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated application settings loaded from environment or .env."""

    mongodb_uri: str = Field(default="mongodb://localhost:27017", min_length=1)
    mongodb_db_name: str = Field(default="lexora_db", min_length=1)
    host: str = Field(default="0.0.0.0", min_length=1)
    port: PositiveInt = 8000
    environment: str = Field(default="development", min_length=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()


settings = get_settings()
