from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from rmf2_scheduler import LockedScheduleRO
from rmf2_scheduler.cache import Action, ActionPayload, ScheduleCache
from rmf2_scheduler.data import Process, Time, action_type

from rmf2_task_scheduler.api.deps.scheduler import SchedulerDep
from rmf2_task_scheduler.model_utils import PyModel
from rmf2_task_scheduler.models import Message
from rmf2_task_scheduler.models import ProcessCreate as ProcessCreateSchema
from rmf2_task_scheduler.models import ProcessUpdate as ProcessUpdateSchema

router = APIRouter()


@router.get("/")
def read_processes(
    task_scheduler: SchedulerDep,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    offset: int = 0,
    limit: int = 100,
) -> list[PyModel[Process]]:
    schedule_cache: ScheduleCache = LockedScheduleRO(task_scheduler).cache()
    query_start_time = Time(start_time) if start_time else Time(datetime.now() - timedelta(days=1))
    query_end_time = Time(end_time) if end_time else Time(datetime.now() + timedelta(days=1))

    tasks = schedule_cache.lookup_tasks(query_start_time, query_end_time)

    process_map: dict[str, Process] = {}
    for task in tasks:
        if task.process_id is None or task.process_id in process_map:
            continue
        process_map[task.process_id] = schedule_cache.get_process(task.process_id)

    return list(process_map.values())


@router.post("/")
def create_process(
    task_scheduler: SchedulerDep,
    process_create: ProcessCreateSchema,
) -> PyModel[Process]:
    process_j = process_create.model_dump(mode="json")
    process_j["id"] = str(uuid4())

    try:
        process_data = Process.from_json(process_j)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    action = Action.create(action_type.PROCESS_ADD, ActionPayload().process(process_data))
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    schedule_cache: ScheduleCache = LockedScheduleRO(task_scheduler).cache()
    return schedule_cache.get_process(process_data.id)


@router.post("/add_dependency", response_model=Message)
def add_dependency_to_process(
    task_scheduler: SchedulerDep,
    source_uuid: str,
    destination_uuid: str,
    edge_type: str = "hard",
) -> Message:
    payload = ActionPayload()
    payload.source_id(source_uuid)
    payload.destination_id(destination_uuid)
    payload.edge_type(edge_type)

    action = Action.create(action_type.PROCESS_ADD_DEPENDENCY, payload)
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    return Message(message="Process updated successfully!")


@router.post("/delete_dependency", response_model=Message)
def delete_dependency_from_process(
    task_scheduler: SchedulerDep,
    source_uuid: str,
    destination_uuid: str,
) -> Message:
    payload = ActionPayload()
    payload.source_id(source_uuid)
    payload.destination_id(destination_uuid)

    action = Action.create(action_type.PROCESS_DELETE_DEPENDENCY, payload)
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    return Message(message="Process updated successfully!")


@router.get("/{uuid}")
def read_process(task_scheduler: SchedulerDep, uuid: str) -> PyModel[Process]:
    schedule_cache: ScheduleCache = LockedScheduleRO(task_scheduler).cache()

    if not schedule_cache.has_process(uuid):
        raise HTTPException(status_code=404, detail="Process doesn't exist")

    return schedule_cache.get_process(uuid)


@router.post("/{uuid}/attach_node", response_model=Message)
def attach_node_to_process(task_scheduler: SchedulerDep, uuid: str, node_uuid: str) -> Message:
    action = Action.create(
        action_type.PROCESS_ATTACH_NODE, ActionPayload().id(uuid).node_id(node_uuid)
    )
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    return Message(message="Process updated successfully!")


@router.post("/{uuid}/detach_node", response_model=Message)
def detach_node_from_process(task_scheduler: SchedulerDep, uuid: str, node_uuid: str) -> Message:
    action = Action.create(
        action_type.PROCESS_DETACH_NODE, ActionPayload().id(uuid).node_id(node_uuid)
    )
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    return Message(message="Process updated successfully!")


@router.put("/{uuid}", response_model=Message)
def update_process(
    task_scheduler: SchedulerDep, uuid: str, process_update: ProcessUpdateSchema
) -> Message:
    process_j = process_update.model_dump(mode="json")
    process_j["id"] = uuid

    try:
        process_data = Process.from_json(process_j)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    action = Action.create(action_type.PROCESS_UPDATE, ActionPayload().process(process_data))
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    return Message(message="Process updated successfully!")


@router.delete("/{uuid}", response_model=Message)
def delete_process(task_scheduler: SchedulerDep, uuid: str, delete_all: bool = False) -> Message:
    action_type_name = action_type.PROCESS_DELETE_ALL if delete_all else action_type.PROCESS_DELETE
    action = Action.create(action_type_name, ActionPayload().id(uuid))
    result, error = task_scheduler.perform(action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    return Message(message="Process delete successfully!")


@router.get(
    "/process_completion/{uuid}",
    response_model=bool,
    response_model_exclude_unset=True,
    response_model_exclude_none=True,
)
def process_completion(task_scheduler: SchedulerDep, uuid: str) -> bool:
    schedule_cache: ScheduleCache = LockedScheduleRO(task_scheduler).cache()

    if not schedule_cache.has_process(uuid):
        raise HTTPException(status_code=404, detail="Process doesn't exist")

    process = schedule_cache.get_process(uuid)
    for task_id in process.graph.get_all_nodes():
        task = schedule_cache.get_task(task_id)
        if task.status != "completed":
            return False
    return True
