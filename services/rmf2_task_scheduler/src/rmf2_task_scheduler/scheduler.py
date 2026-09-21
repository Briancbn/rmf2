from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from rmf2_scheduler import (
    Scheduler,
    SchedulerOptions,
    SystemTimeExecutor,
    TaskExecutorManager,
    TaskflowProcessExecutor,
)
from rmf2_scheduler.data import Duration
from rmf2_scheduler.storage import ScheduleStream

from .config import Settings
from .logger import get_logger
from .sql_schedule_stream import SQLScheduleStream

LOGGER = get_logger(__name__)


@dataclass
class SchedulerContext:
    scheduler: Scheduler
    system_time_executor: SystemTimeExecutor
    task_executor_manager: TaskExecutorManager
    process_executor: TaskflowProcessExecutor
    stream: ScheduleStream
    thread: threading.Thread


def _make_options(config: Settings) -> SchedulerOptions:
    options = SchedulerOptions()
    options.runtime_tick_period(Duration(config.scheduler.runtime_tick_period))
    options.static_cache_period(Duration(config.scheduler.static_cache_period))
    return options


def _make_stream(config: Settings) -> ScheduleStream:
    if config.schedule_stream_mode == "sql":
        return SQLScheduleStream(config.database_url)
    if config.schedule_stream_mode == "ld_broker":
        return ScheduleStream.create_default(config.schedule_stream_path)
    return ScheduleStream.create_simple(
        config.schedule_stream_shards, config.schedule_stream_path
    )


@contextmanager
def make_scheduler(config: Settings) -> Generator[SchedulerContext, None, None]:
    options = _make_options(config)
    stream = _make_stream(config)
    system_time_executor = SystemTimeExecutor()
    task_executor_manager = TaskExecutorManager()
    process_executor = TaskflowProcessExecutor(
        task_executor_manager, config.scheduler.process_executor_concurrency
    )

    scheduler = Scheduler(
        options,
        stream,
        system_time_executor,
        process_executor=process_executor,
        task_executor_manager=task_executor_manager,
    )

    thread = threading.Thread(target=system_time_executor.spin, daemon=True)
    LOGGER.info("Starting scheduler (mode=%s, path=%s)", config.schedule_stream_mode, config.schedule_stream_path)
    thread.start()

    try:
        yield SchedulerContext(
            scheduler=scheduler,
            system_time_executor=system_time_executor,
            task_executor_manager=task_executor_manager,
            process_executor=process_executor,
            stream=stream,
            thread=thread,
        )
    finally:
        LOGGER.info("Stopping scheduler")
        system_time_executor.stop()
        thread.join()
