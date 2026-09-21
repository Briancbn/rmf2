"""Round-trip pydantic TaskCreate <-> native rmf2_scheduler Task.from_json()/.json()."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from rmf2_scheduler.data import Task as NativeTask

from rmf2_task_scheduler.models import TaskCreate


def test_task_create_round_trips_through_native_task() -> None:
    task_create = TaskCreate(type="demo", start_time=datetime.now())

    task_j = task_create.model_dump(mode="json")
    task_j["id"] = str(uuid4())
    task_j["status"] = ""

    native_task = NativeTask.from_json(task_j)

    assert native_task.id == task_j["id"]
    assert native_task.type == "demo"
    assert native_task.status == ""
    assert native_task.json()["id"] == task_j["id"]
