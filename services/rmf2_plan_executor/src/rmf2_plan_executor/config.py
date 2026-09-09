from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field
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

_MODE = os.environ.get("MODE", "dev")
_ENV_FILES = [".env", f".env.{_MODE}"]
_TOML_FILES = ["config.toml", f"config.{_MODE}.toml"]


class AmqpSettings(BaseModel):
    url: str = "amqp://guest:guest@localhost/"
    exchange: str = "rmf2"


class VmSettings(BaseModel):
    base_url: str = "http://localhost:8000"


class AgentConfig(BaseModel):
    agent_id: str
    manufacturer: str
    serial_number: str


class Settings(BaseSettings):
    """RMF2 Plan Executor service configuration.

    Settings are loaded in priority order: CLI args > env vars > .env file > config.toml > defaults.

    Environment-specific overrides are selected via the MODE env var (default: dev):
      .env.<MODE>        e.g. .env.dev, .env.staging, .env.prod
      config.<MODE>.toml e.g. config.dev.toml, config.staging.toml, config.prod.toml
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        env_prefix="RMF2_PE__",
        env_nested_delimiter="__",
        toml_file=_TOML_FILES,
    )

    host: str = Field(default="0.0.0.0", description="Host address for the FastAPI server to bind to")
    port: int = Field(default=8000, description="Port for the FastAPI server to listen on")
    root_path: str = Field(default="", description="ASGI root_path when running behind a reverse proxy with a path prefix")
    cors_origins: list[str] = Field(default=["*"], description="Allowed CORS origins")
    amqp: AmqpSettings = Field(default_factory=AmqpSettings)
    vm: VmSettings = Field(default_factory=VmSettings)
    agents: List[AgentConfig] = Field(default=[], description="Agent-to-VDA5050 mappings")
    map_path: Path | None = None

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
