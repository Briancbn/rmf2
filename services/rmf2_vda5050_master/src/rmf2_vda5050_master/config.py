from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    CliSettingsSource,
    DotEnvSettingsSource,
    EnvSettingsSource,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from .models import AgvConfig

_MODE = os.environ.get("MODE", "dev")
_ENV_FILES = [".env", f".env.{_MODE}"]
_TOML_FILES = ["config.toml", f"config.{_MODE}.toml"]


class Settings(BaseSettings):
    """RMF2 VDA5050 Master service configuration.

    Settings are loaded in priority order: CLI args > env vars > .env file > config.toml > defaults.

    Environment-specific overrides are selected via the MODE env var (default: dev):
      .env.<MODE>        e.g. .env.dev, .env.staging, .env.prod
      config.<MODE>.toml e.g. config.dev.toml, config.staging.toml, config.prod.toml

    AGV configurations are best defined in config.<MODE>.toml as [[agvs]] tables.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        env_prefix="RMF2_VM__",
        toml_file=_TOML_FILES,
    )

    database_url: str = Field(default="sqlite:///./rmf2_vda5050_master.db", description="SQLAlchemy database URL. Defaults to a local SQLite file; use a postgresql:// URL for PostgreSQL")
    mqtt_broker: str = Field(description="MQTT broker URI (e.g. tcp://localhost:1883)")
    master_mqtt_client_id: str | None = Field(default=None, description="MQTT client ID used by this master node. Defaults to rmf2-vda5050-master if not set")
    agvs: list[AgvConfig] = Field(default=[], description="List of AGVs to onboard. Preferred: config.<MODE>.toml [[agvs]] table")
    host: str = Field(description="Host address for the FastAPI server to bind to")
    port: int = Field(description="Port for the FastAPI server to listen on")
    cors_origins: list[str] = Field(default=["*"], description="Allowed CORS origins")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: InitSettingsSource,
        env_settings: EnvSettingsSource,
        dotenv_settings: DotEnvSettingsSource,
        **_: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            CliSettingsSource(settings_cls, cli_parse_args=True, cli_kebab_case=True),
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            init_settings,
        )


@lru_cache
def settings() -> Settings:
    return Settings()
