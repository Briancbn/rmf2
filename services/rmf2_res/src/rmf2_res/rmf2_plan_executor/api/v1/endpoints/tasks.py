from fastapi import APIRouter, HTTPException

from rmf2_res import crud
from rmf2_res.models import TaskRecordStatus
from rmf2_res.rmf2_plan_executor.api.deps.db import DbSession

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model_exclude_none=True)
def get_task_statuses(db: DbSession, skip: int = 0, limit: int = 100) -> list[TaskRecordStatus]:
    records = crud.task_record.get_multi(db, skip=skip, limit=limit)
    return [TaskRecordStatus.model_validate(record) for record in records]


@router.get("/{task_id}", response_model_exclude_none=True)
def get_task_status(task_id: str, db: DbSession) -> TaskRecordStatus:
    record = crud.task_record.get(db, task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskRecordStatus.model_validate(record)
