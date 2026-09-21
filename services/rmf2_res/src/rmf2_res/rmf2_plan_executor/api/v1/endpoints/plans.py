import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from res_mapf_planning.traffic_dependencies.models.plan import Plan

from rmf2_res import crud
from rmf2_res.models import PlanRecordStatus
from rmf2_res.rmf2_plan_executor.api.deps.db import DbSession
from rmf2_res.rmf2_plan_executor.api.deps.transport import TransportDeps
from rmf2_res.transport import JsonSerializer

router = APIRouter(prefix="/plans", tags=["plans"])


class PlanInjectResponse(BaseModel):
    status: str
    robot_id: str


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


@router.post("/{robot_id}")
def inject_plan(robot_id: str, body: dict, transport: TransportDeps) -> PlanInjectResponse:
    """Inject a plan directly for a robot, bypassing the plan server AMQP path.

    The request body must be a serialised Plan object matching the res_mapf Plan JSON schema.
    """
    try:
        plan = JsonSerializer().deserialize(json.dumps(body), Plan)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid plan body: {exc}") from exc
    transport.submit_plan(robot_id, plan)
    return PlanInjectResponse(status="published", robot_id=robot_id)
