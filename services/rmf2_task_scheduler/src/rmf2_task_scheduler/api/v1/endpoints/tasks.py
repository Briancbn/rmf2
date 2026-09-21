from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from rmf2_scheduler import LockedScheduleRO
from rmf2_scheduler.cache import Action, ActionPayload, ScheduleCache
from rmf2_scheduler.data import Task, Time, action_type

from rmf2_task_scheduler.api.deps.scheduler import SchedulerDep
from rmf2_task_scheduler.model_utils import PyModel
from rmf2_task_scheduler.models import Message
from rmf2_task_scheduler.models import TaskCreate as TaskCreateSchema
from rmf2_task_scheduler.models import TaskUpdate as TaskUpdateSchema

router = APIRouter()


@router.get("/")
def read_tasks(
    task_scheduler: SchedulerDep,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    offset: int = 0,
    limit: int = 100,
) -> list[PyModel[Task]]:
    start_time = start_time or datetime.now()
    end_time = end_time or datetime.now() + timedelta(days=1)

    schedule_cache: ScheduleCache = LockedScheduleRO(task_scheduler).cache()
    return schedule_cache.lookup_tasks(Time(start_time), Time(end_time))


@router.post("/")
def create_task(
    task_scheduler: SchedulerDep,
    task_create: TaskCreateSchema,
) -> PyModel[Task]:
    task_j = task_create.model_dump(mode="json")
    task_j["id"] = str(uuid4())
    task_j["status"] = ""

    try:
        task_data = Task.from_json(task_j)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    action = Action.create(action_type.TASK_ADD, ActionPayload().task(task_data))
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    schedule_cache: ScheduleCache = LockedScheduleRO(task_scheduler).cache()
    return schedule_cache.get_task(task_data.id)


@router.get("/{uuid}")
def read_task(task_scheduler: SchedulerDep, uuid: str) -> PyModel[Task]:
    schedule_cache: ScheduleCache = LockedScheduleRO(task_scheduler).cache()

    if not schedule_cache.has_task(uuid):
        raise HTTPException(status_code=404, detail="Task doesn't exist")

    return schedule_cache.get_task(uuid)


@router.put("/{uuid}", response_model=Message)
def update_task(
    task_scheduler: SchedulerDep,
    uuid: str,
    task_update: TaskUpdateSchema,
) -> Message:
    task_j = task_update.model_dump(mode="json")
    task_j["id"] = uuid
    task_j["status"] = ""

    try:
        task_data = Task.from_json(task_j)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    action = Action.create(action_type.TASK_UPDATE, ActionPayload().task(task_data))
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    return Message(message="Task updated successfully!")


@router.delete("/{uuid}", response_model=Message)
def delete_task(task_scheduler: SchedulerDep, uuid: str) -> Message:
    action = Action.create(action_type.TASK_DELETE, ActionPayload().id(uuid))
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    return Message(message="Task delete successfully!")
