from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from rmf2_scheduler.cache import Action
from rmf2_scheduler.data import ScheduleAction, Time

from rmf2_task_scheduler.api.deps.scheduler import SchedulerDep
from rmf2_task_scheduler.models import Message
from rmf2_task_scheduler.models import Schedule as ScheduleSchema
from rmf2_task_scheduler.models import ScheduleAction as ScheduleActionSchema

router = APIRouter()


@router.get(
    "/",
    response_model=ScheduleSchema,
    response_model_exclude_unset=True,
    response_model_exclude_none=True,
)
def read_schedule(
    task_scheduler: SchedulerDep,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    offset: int = 0,
    limit: int = 100,
) -> ScheduleSchema:
    query_start_time = Time(start_time) if start_time else Time(datetime.now() - timedelta(days=1))
    query_end_time = Time(end_time) if end_time else Time(datetime.now() + timedelta(days=1))

    result, error, tasks, processes, _ = task_scheduler.get_schedule(
        query_start_time, query_end_time, offset, limit
    )

    if not result:
        raise HTTPException(status_code=404, detail=error)

    return ScheduleSchema(tasks=list(tasks), processes=list(processes))


def _to_cache_action(action: ScheduleActionSchema) -> Action:
    action_j = action.model_dump(mode="json")
    if action_j.get("task"):
        action_j["task"]["status"] = ""

    try:
        return Action.create(ScheduleAction.from_json(action_j))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/edit", response_model=Message)
def edit_schedule(
    task_scheduler: SchedulerDep, action: ScheduleActionSchema, dry_run: bool = True
) -> Message:
    """
    Edit Schedule.

    Allowed actions types and their payloads are as follows

    | type                      | payloads                                             |
    | ------------------------- | ---------------------------------------------------- |
    | EVENT_ADD                 | event                                                |
    | EVENT_UPDATE              | event                                                |
    | EVENT_DELETE              | id                                                   |
    | TASK_ADD                  | task                                                 |
    | TASK_UPDATE               | task                                                 |
    | TASK_DELETE               | id                                                   |
    | PROCESS_ADD               | process                                              |
    | PROCESS_UPDATE            | process                                              |
    | PROCESS_ATTACH_NODE       | id, node_id                                          |
    | PROCESS_DETACH_NODE       | id, node_id                                          |
    | PROCESS_UPDATE_START_TIME | id                                                   |
    | PROCESS_ADD_DEPENDENCY    | source_id, destination_id, edge_type                 |
    | PROCESS_DELETE_DEPENDENCY | source_id, destination_id                            |
    | PROCESS_DELETE            | id                                                   |
    | PROCESS_DELETE_ALL        | id                                                   |

    Below is an example of a selected action
    - type: **PROCESS_ADD_DEPENDENCY**
    - payloads: **source_id**, **destination_id**

    ```json
    {
        "type": "PROCESS_ADD_DEPENDENCY",
        "source_id": "<uuid>",
        "destination_id": "<uuid>"
    }
    ```
    """
    cache_action = _to_cache_action(action)

    if dry_run:
        result, error = task_scheduler.validate(cache_action)
        if not result:
            raise HTTPException(status_code=404, detail=error)
        return Message(message="Dry run successfully.")

    result, error = task_scheduler.perform(cache_action)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    return Message(message="Schedule updated successfully!")


@router.post("/edit/batch", response_model=Message)
def batch_edit_schedule(
    task_scheduler: SchedulerDep,
    actions: list[ScheduleActionSchema],
    dry_run: bool = True,
) -> Message:
    cache_actions = [_to_cache_action(action) for action in actions]

    if dry_run:
        result, error = task_scheduler.validate_batch(cache_actions)
        if not result:
            raise HTTPException(status_code=404, detail=error)
        return Message(message="Dry run successfully.")

    result, error = task_scheduler.perform_batch(cache_actions)
    if not result:
        raise HTTPException(status_code=404, detail=error)

    return Message(message="Schedule updated successfully!")
