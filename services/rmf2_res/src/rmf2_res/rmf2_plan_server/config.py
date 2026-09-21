from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from pydantic import BaseModel
from res_plan_server.transport.transport_messages import RobotOnboardMsg
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


class AgvInitConfig(BaseModel):
    x: float | None = None
    y: float | None = None
    theta: float | None = None
    last_node_id: str | None = None
    map_id: str | None = None


class AgvConfig(BaseModel):
    """Mirrors vda5050_master's `[[agvs]]` config.toml table, so the same file
    can onboard robots here via the `agvs` alias for `robots`."""

    manufacturer: str
    serial_number: str
    init_config: AgvInitConfig | None = None

    def to_robot_onboard_msg(self) -> RobotOnboardMsg:
        return RobotOnboardMsg(
            robot_id=f"{self.manufacturer}/{self.serial_number}",
            start_location=(self.init_config.last_node_id if self.init_config else None) or "",
        )


class Settings(BaseSettings):
    """RMF2 Plan Server service configuration.

    Settings are loaded in priority order: CLI args > env vars > .env file > config.toml > defaults.

    Environment-specific overrides are selected via the MODE env var (default: dev):
      .env.<MODE>        e.g. .env.dev, .env.staging, .env.prod
      config.<MODE>.toml e.g. config.dev.toml, config.staging.toml, config.prod.toml
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        env_prefix="RMF2_PS__",
        env_nested_delimiter="__",
        toml_file=_TOML_FILES,
        extra="ignore",
    )

    host: str = Field(default="0.0.0.0", description="Host address for the FastAPI server to bind to")
    port: int = Field(default=8000, description="Port for the FastAPI server to listen on")
    root_path: str = Field(default="", description="ASGI root_path when running behind a reverse proxy with a path prefix (e.g. /res)")
    cors_origins: list[str] = Field(default=["*"], description="Allowed CORS origins")
    transport: Literal["amqp", "zenoh"] | None = Field(
        default=None,
        description="Transport backend to use. One of: amqp, zenoh. Omit or set to null to run without a transport (HTTP-only mode).",
    )
    amqp: AmqpSettings = Field(default_factory=AmqpSettings, description="AMQP transport settings")
    plan_executor_topic_prefix: str = Field(
        default="rmf2_plan_executor/v1",
        description="AMQP topic prefix used to address the plan_executor (committed_locations, plan dispatch, plan_progress/error, task_status).",
    )
    map_path: Path | None = Field(default=None, description="Path to LIF JSON map file")
    robots: list[RobotOnboardMsg] = Field(default_factory=list, description="Robots to onboard on startup")
    agvs: list[AgvConfig] = Field(
        default_factory=list,
        description="Alias for `robots`, using vda5050_master's config.toml [[agvs]] schema "
        "(manufacturer/serial_number/init_config.last_node_id). Converted and appended to `robots`.",
    )
    database_url: str = Field(
        default="sqlite:///./rmf2_plan_server.db",
        description="SQLAlchemy database URL for tracking onboarded robots",
    )

    @model_validator(mode="after")
    def _merge_agvs_alias(self) -> Settings:
        if self.agvs:
            self.robots = [*self.robots, *(agv.to_robot_onboard_msg() for agv in self.agvs)]
        return self

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
