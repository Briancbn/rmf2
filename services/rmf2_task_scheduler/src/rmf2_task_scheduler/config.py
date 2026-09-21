from __future__ import annotations

import os
from datetime import timedelta
from functools import lru_cache
from typing import Literal

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


class SchedulerSettings(BaseModel):
    """Options passed into ``rmf2_scheduler.SchedulerOptions``.

    TOML::

        [scheduler]
        runtime_tick_period_seconds = 300
        static_cache_period_seconds = 3600

    Env vars (prefix ``RMF2_TS__SCHEDULER__``)::

        RMF2_TS__SCHEDULER__RUNTIME_TICK_PERIOD_SECONDS=300
        RMF2_TS__SCHEDULER__STATIC_CACHE_PERIOD_SECONDS=3600
    """

    runtime_tick_period_seconds: float = 300.0
    static_cache_period_seconds: float = 3600.0
    process_executor_concurrency: int | None = Field(
        default=None,
        description="Max concurrent threads for the TaskflowProcessExecutor. "
        "Defaults to std::thread::hardware_concurrency() when unset.",
    )

    @property
    def runtime_tick_period(self) -> timedelta:
        return timedelta(seconds=self.runtime_tick_period_seconds)

    @property
    def static_cache_period(self) -> timedelta:
        return timedelta(seconds=self.static_cache_period_seconds)


class Settings(BaseSettings):
    """RMF2 Task Scheduler service configuration.

    Settings are loaded in priority order: CLI args > env vars > .env file > config.toml > defaults.

    Environment-specific overrides are selected via the MODE env var (default: dev):
      .env.<MODE>        e.g. .env.dev, .env.staging, .env.prod
      config.<MODE>.toml e.g. config.dev.toml, config.staging.toml, config.prod.toml
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        env_prefix="RMF2_TS__",
        env_nested_delimiter="__",
        toml_file=_TOML_FILES,
    )

    host: str = Field(description="Host address for the FastAPI server to bind to")
    port: int = Field(description="Port for the FastAPI server to listen on")
    root_path: str = Field(default="", description="ASGI root_path when running behind a reverse proxy with a path prefix (e.g. /task_scheduler)")
    cors_origins: list[str] = Field(default=["*"], description="Allowed CORS origins")

    schedule_stream_mode: Literal["simple", "ld_broker", "sql"] = Field(
        default="sql",
        description=(
            "'simple': persist to a local backup directory via "
            "storage.ScheduleStream.create_simple(schedule_stream_shards, schedule_stream_path). "
            "'ld_broker': fetch/persist via a remote linked-data broker HTTP endpoint at "
            "schedule_stream_path (a URL), via storage.ScheduleStream.create_default(url). "
            "'sql': persist tasks/processes/series to database_url via a Python "
            "SQLAlchemy-backed ScheduleStream subclass (rmf2_task_scheduler.sql_schedule_stream)."
        ),
    )
    schedule_stream_path: str = Field(
        default="data/schedule_stream",
        description="Local directory ('simple' mode) or broker URL ('ld_broker' mode) for schedule persistence",
    )
    schedule_stream_shards: int = Field(
        default=1,
        description="Shard count, only used when schedule_stream_mode == 'simple'",
    )
    database_url: str = Field(
        default="sqlite:///./rmf2_task_scheduler.db",
        description="SQLAlchemy database URL, only used when schedule_stream_mode == 'sql'",
    )

    scheduler: SchedulerSettings = Field(
        default_factory=SchedulerSettings, description="Native Scheduler options"
    )

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
