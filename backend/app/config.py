from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_dir: Path = Field(default=Path("./data"), validation_alias="DATA_DIR")
    fastf1_cache_dir: Path = Field(
        default=Path("./data/cache/fastf1"), validation_alias="FASTF1_CACHE_DIR"
    )
    openf1_base_url: str = Field(
        default="https://api.openf1.org/v1", validation_alias="OPENF1_BASE_URL"
    )
    openf1_api_key: str | None = Field(default=None, validation_alias="OPENF1_API_KEY")
    enable_live_mode: bool = Field(default=False, validation_alias="ENABLE_LIVE_MODE")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"], validation_alias="CORS_ORIGINS"
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> list[str]:
        if value is None:
            return ["http://localhost:3000"]
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        if isinstance(value, list):
            return value
        raise ValueError("CORS_ORIGINS must be a comma-separated string or a list")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.fastf1_cache_dir.mkdir(parents=True, exist_ok=True)
    return settings

