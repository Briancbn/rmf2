from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from rmf2_scheduler import LockedScheduleRO
from rmf2_scheduler.cache import Action, ActionPayload, ScheduleCache
from rmf2_scheduler.data import Series, Time, action_type

from rmf2_task_scheduler.api.deps.scheduler import SchedulerDep
from rmf2_task_scheduler.model_utils import PyModel
from rmf2_task_scheduler.models import Message
from rmf2_task_scheduler.models import SeriesCreate as SeriesCreateSchema

router = APIRouter()


@router.get("/")
def read_series(
    task_scheduler: SchedulerDep,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    offset: int = 0,
    limit: int = 100,
) -> list[PyModel[Series]]:
    schedule_cache: ScheduleCache = LockedScheduleRO(task_scheduler).cache()
    query_start_time = Time(start_time) if start_time else Time(datetime.now() - timedelta(days=1))

    try:
        return schedule_cache.lookup_series(query_start_time)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/")
def create_series(
    task_scheduler: SchedulerDep,
    series_create: SeriesCreateSchema,
) -> PyModel[Series]:
    series_j = series_create.model_dump(mode="json")
    series_j["id"] = str(uuid4())

    try:
        series_data = Series.from_json(series_j)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    action = Action.create(action_type.SERIES_ADD, ActionPayload().series(series_data))
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    schedule_cache: ScheduleCache = LockedScheduleRO(task_scheduler).cache()
    return schedule_cache.get_series(series_data.id())


@router.put("/update_occurrence_time", response_model=Message)
def update_occurrence_time(
    task_scheduler: SchedulerDep,
    series_id: str,
    occurrence_id: str,
    occurrence_time: datetime,
) -> Message:
    action = Action.create(
        action_type.SERIES_UPDATE_OCCURRENCE_TIME,
        ActionPayload()
        .id(series_id)
        .occurrence_id(occurrence_id)
        .occurrence_time(Time(occurrence_time)),
    )
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    return Message(message="Task updated successfully!")


@router.delete("/{uuid}", response_model=Message)
def delete_series(task_scheduler: SchedulerDep, uuid: str) -> Message:
    action = Action.create(action_type.SERIES_DELETE, ActionPayload().id(uuid))
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    return Message(message="Series delete successfully!")


@router.delete("/occurrence", response_model=Message)
def delete_series_occurrence(
    task_scheduler: SchedulerDep,
    series_id: str,
    occurrence_id: str,
) -> Message:
    action = Action.create(
        action_type.SERIES_DELETE_OCCURRENCE,
        ActionPayload().id(series_id).occurrence_id(occurrence_id),
    )
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    return Message(message="Task delete successfully!")
