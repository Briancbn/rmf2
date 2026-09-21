from fastapi import APIRouter, HTTPException

from rmf2_res import crud
from rmf2_res.models import PlanCacheEntry, PlanRecordStatus
from rmf2_res.rmf2_plan_server.api.deps.context import ContextDeps
from rmf2_res.rmf2_plan_server.api.deps.db import DbSession

router = APIRouter()


@router.get("/cache")
def get_plan_cache(context: ContextDeps) -> list[PlanCacheEntry]:
    if context.plan_cache is None:
        return []
    problem, cached = context.plan_cache
    return [
        PlanCacheEntry(
            problem=[{"robot_id": robot_id, "goal": goal} for robot_id, goal in sorted(problem.items())],
            plans={robot_id: plan for robot_id, (plan, _) in cached.items()},
        )
    ]


@router.get("", response_model_exclude_none=True)
def get_plan_statuses(db: DbSession, skip: int = 0, limit: int = 100) -> list[PlanRecordStatus]:
    records = crud.plan_record.get_multi(db, skip=skip, limit=limit)
    return [PlanRecordStatus.model_validate(record) for record in records]


@router.get("/{plan_id}", response_model_exclude_none=True)
def get_plan_status(plan_id: str, db: DbSession) -> PlanRecordStatus:
    record = crud.plan_record.get(db, plan_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return PlanRecordStatus.model_validate(record)
