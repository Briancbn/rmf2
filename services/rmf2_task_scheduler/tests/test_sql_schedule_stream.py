"""SQLScheduleStream: upsert-on-add, soft-delete-on-delete, read_schedule round trip."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from rmf2_scheduler import cache
from rmf2_scheduler.data import Task, Time, TimeWindow, action_type

from rmf2_task_scheduler.sql_schedule_stream import SQLScheduleStream, TaskEntity


def _make_stream(tmp_path) -> SQLScheduleStream:
    return SQLScheduleStream(f"sqlite:///{tmp_path / 'test.db'}")


def _add_task(live_cache: cache.ScheduleCache, task_id: str) -> cache.Action:
    task_j = {
        "id": task_id,
        "type": "demo",
        "status": "",
        "start_time": datetime.now().isoformat(),
    }
    task_data = Task.from_json(task_j)
    action = cache.Action.create(action_type.TASK_ADD, cache.ActionPayload().task(task_data))
    ok, error = action.validate(live_cache)
    assert ok, error
    action.apply()
    return action


def test_add_then_delete_is_soft_delete(tmp_path) -> None:
    stream = _make_stream(tmp_path)
    live_cache = cache.ScheduleCache()
    task_id = str(uuid.uuid4())

    add_action = _add_task(live_cache, task_id)
    ok, error = stream.write_schedule(live_cache, [add_action.record()])
    assert ok, error

    with stream._session_factory() as session:
        row = session.get(TaskEntity, task_id)
        assert row is not None
        assert row.deleted_at is None
        assert row.payload["type"] == "demo"

    delete_action = cache.Action.create(action_type.TASK_DELETE, cache.ActionPayload().id(task_id))
    ok, error = delete_action.validate(live_cache)
    assert ok, error
    delete_action.apply()

    ok, error = stream.write_schedule(live_cache, [delete_action.record()])
    assert ok, error

    with stream._session_factory() as session:
        row = session.get(TaskEntity, task_id)
        assert row is not None, "soft-delete must not remove the row"
        assert row.deleted_at is not None


def test_read_schedule_excludes_soft_deleted_tasks(tmp_path) -> None:
    stream = _make_stream(tmp_path)
    live_cache = cache.ScheduleCache()
    task_id = str(uuid.uuid4())

    add_action = _add_task(live_cache, task_id)
    ok, error = stream.write_schedule(live_cache, [add_action.record()])
    assert ok, error

    delete_action = cache.Action.create(action_type.TASK_DELETE, cache.ActionPayload().id(task_id))
    ok, error = delete_action.validate(live_cache)
    assert ok, error
    delete_action.apply()
    ok, error = stream.write_schedule(live_cache, [delete_action.record()])
    assert ok, error

    fresh_cache = cache.ScheduleCache()
    time_window = TimeWindow()
    time_window.start = Time(datetime.now() - timedelta(days=1))
    time_window.end = Time(datetime.now() + timedelta(days=1))

    ok, error = stream.read_schedule(fresh_cache, time_window)
    assert ok, error
    assert not fresh_cache.has_task(task_id)


def test_read_schedule_reconstructs_active_tasks(tmp_path) -> None:
    stream = _make_stream(tmp_path)
    live_cache = cache.ScheduleCache()
    task_id = str(uuid.uuid4())

    add_action = _add_task(live_cache, task_id)
    ok, error = stream.write_schedule(live_cache, [add_action.record()])
    assert ok, error

    fresh_cache = cache.ScheduleCache()
    time_window = TimeWindow()
    time_window.start = Time(datetime.now() - timedelta(days=1))
    time_window.end = Time(datetime.now() + timedelta(days=1))

    ok, error = stream.read_schedule(fresh_cache, time_window)
    assert ok, error
    assert fresh_cache.has_task(task_id)
    assert fresh_cache.get_task(task_id).json()["type"] == "demo"
