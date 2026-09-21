"""SQLAlchemy-backed rmf2_scheduler.storage.ScheduleStream.

Subclassing ScheduleStream from Python requires the pybind11 trampoline
added on the ``feat/bn/schedule-stream-py-trampoline`` branch of
Briancbn/rmf_scheduler (see pyproject.toml's [tool.uv.sources]) -- without
it, ScheduleStream has no py::init() and cannot be constructed/subclassed
in Python at all.

Storage model: three tables (tasks, processes, series) -- events aren't
persisted since this service never ported the (upstream-legacy) events
API. Each row holds the native object's full .json() blob. Deletions are
soft (``deleted_at`` set), never a real SQL DELETE.

read_schedule populates the given (initially empty) ScheduleCache the same
way the rest of this codebase mutates caches: build a cache.Action, call
.validate(cache), then .apply() -- ScheduleCache exposes no direct "insert"
method to Python; mutation is gated through the friended Action subclasses.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from rmf2_scheduler.cache import Action, ActionPayload, ScheduleCache
from rmf2_scheduler.data import (
    Process,
    ScheduleChangeRecord,
    Series,
    Task,
    TimeWindow,
    action_type,
    record_action_type,
    record_data_type,
)
from rmf2_scheduler.storage import ScheduleStream
from sqlalchemy import JSON, DateTime, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class TaskEntity(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ProcessEntity(Base):
    __tablename__ = "processes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class SeriesEntity(Base):
    __tablename__ = "series"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


_TABLE = {"task": TaskEntity, "process": ProcessEntity, "series": SeriesEntity}
_ADD_ACTION_TYPE = {
    "task": action_type.TASK_ADD,
    "process": action_type.PROCESS_ADD,
    "series": action_type.SERIES_ADD,
}
_FROM_JSON = {"task": Task.from_json, "process": Process.from_json, "series": Series.from_json}
_PAYLOAD_SETTER = {
    "task": lambda payload, obj: payload.task(obj),
    "process": lambda payload, obj: payload.process(obj),
    "series": lambda payload, obj: payload.series(obj),
}
_GET_FROM_CACHE = {
    "task": lambda cache, id_: cache.get_task(id_) if cache.has_task(id_) else None,
    "process": lambda cache, id_: cache.get_process(id_) if cache.has_process(id_) else None,
    "series": lambda cache, id_: cache.get_series(id_) if cache.has_series(id_) else None,
}
# Series/processes load before tasks, which may reference them by id.
_ENTITY_LOAD_ORDER = {"series": 0, "process": 1, "task": 2}


def _parse_iso(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


class SQLScheduleStream(ScheduleStream):
    """ScheduleStream backed by a SQLAlchemy engine."""

    def __init__(self, database_url: str) -> None:
        super().__init__()
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self._engine = create_engine(database_url, connect_args=connect_args)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine)

    def read_schedule(self, cache: ScheduleCache, time_window: TimeWindow) -> tuple[bool, str]:
        try:
            with self._session_factory() as session:
                rows: list[Any] = list(
                    session.scalars(
                        select(SeriesEntity).where(SeriesEntity.deleted_at.is_(None))
                    ).all()
                )
                rows += session.scalars(
                    select(ProcessEntity).where(ProcessEntity.deleted_at.is_(None))
                ).all()
                rows += session.scalars(
                    select(TaskEntity)
                    .where(TaskEntity.deleted_at.is_(None))
                    .where(TaskEntity.start_time >= time_window.start.to_ISOtime())
                    .where(TaskEntity.start_time <= time_window.end.to_ISOtime())
                ).all()
        except Exception as exc:  # noqa: BLE001 -- surfaced to the caller via `error`
            return (False, str(exc))

        entity_type_of = {TaskEntity: "task", ProcessEntity: "process", SeriesEntity: "series"}
        rows.sort(key=lambda row: _ENTITY_LOAD_ORDER[entity_type_of[type(row)]])
        for row in rows:
            entity_type = entity_type_of[type(row)]
            ok, error = self._apply_add(cache, entity_type, row.payload)
            if not ok:
                return (False, f"{entity_type} {row.id}: {error}")
        return (True, "")

    def write_schedule(  # type: ignore[override]
        self,
        cache: ScheduleCache,
        second_arg: TimeWindow | Sequence[ScheduleChangeRecord],
    ) -> tuple[bool, str]:
        if isinstance(second_arg, TimeWindow):
            return self._write_snapshot(cache, second_arg)
        return self._write_records(cache, second_arg)

    def refresh_tasks(self, cache: ScheduleCache, ids: Sequence[str]) -> tuple[bool, str]:
        try:
            with self._session_factory() as session:
                rows = session.scalars(
                    select(TaskEntity)
                    .where(TaskEntity.id.in_(list(ids)))
                    .where(TaskEntity.deleted_at.is_(None))
                ).all()
                for row in rows:
                    action_t = action_type.TASK_UPDATE if cache.has_task(row.id) else action_type.TASK_ADD
                    task_obj = Task.from_json(row.payload)
                    action = Action.create(action_t, ActionPayload().task(task_obj))
                    ok, error = action.validate(cache)
                    if not ok:
                        return (False, error)
                    action.apply()
        except Exception as exc:  # noqa: BLE001
            return (False, str(exc))
        return (True, "")

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    def _apply_add(
        self, cache: ScheduleCache, entity_type: str, payload_json: dict[str, Any]
    ) -> tuple[bool, str]:
        obj = _FROM_JSON[entity_type](payload_json)
        payload = _PAYLOAD_SETTER[entity_type](ActionPayload(), obj)
        action = Action.create(_ADD_ACTION_TYPE[entity_type], payload)
        ok, error = action.validate(cache)
        if not ok:
            return (False, error)
        action.apply()
        return (True, "")

    def _upsert(self, session, entity_type: str, id_: str, payload_json: dict[str, Any]) -> None:
        model = _TABLE[entity_type]
        now = datetime.now(timezone.utc)
        row = session.get(model, id_)
        if row is None:
            kwargs: dict[str, Any] = {"id": id_, "payload": payload_json, "updated_at": now}
            if entity_type == "task":
                kwargs["start_time"] = _parse_iso(payload_json.get("start_time"))
            session.add(model(**kwargs))
        else:
            row.payload = payload_json
            row.updated_at = now
            row.deleted_at = None  # un-delete, in case it reappears
            if entity_type == "task":
                row.start_time = _parse_iso(payload_json.get("start_time"))

    def _soft_delete(self, session, entity_type: str, id_: str) -> None:
        model = _TABLE[entity_type]
        row = session.get(model, id_)
        if row is not None:
            row.deleted_at = datetime.now(timezone.utc)

    def _write_snapshot(self, cache: ScheduleCache, time_window: TimeWindow) -> tuple[bool, str]:
        try:
            with self._session_factory() as session:
                for series in cache.lookup_series(time_window.start):
                    self._upsert(session, "series", series.id(), series.json())

                seen_processes: set[str] = set()
                for task in cache.lookup_tasks(time_window.start, time_window.end):
                    self._upsert(session, "task", task.id, task.json())
                    if task.process_id and task.process_id not in seen_processes:
                        seen_processes.add(task.process_id)
                        process = cache.get_process(task.process_id)
                        self._upsert(session, "process", process.id, process.json())

                session.commit()
        except Exception as exc:  # noqa: BLE001
            return (False, str(exc))
        return (True, "")

    def _write_records(
        self, cache: ScheduleCache, records: Sequence[ScheduleChangeRecord]
    ) -> tuple[bool, str]:
        try:
            with self._session_factory() as session:
                for record in records:
                    for entity_type, record_type in (
                        ("task", record_data_type.TASK),
                        ("process", record_data_type.PROCESS),
                        ("series", record_data_type.SERIES),
                    ):
                        for change in record.get(record_type):
                            if change.action == record_action_type.DELETE:
                                self._soft_delete(session, entity_type, change.id)
                                continue
                            obj = _GET_FROM_CACHE[entity_type](cache, change.id)
                            if obj is None:
                                continue
                            self._upsert(session, entity_type, change.id, obj.json())
                session.commit()
        except Exception as exc:  # noqa: BLE001
            return (False, str(exc))
        return (True, "")
