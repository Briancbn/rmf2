import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from rmf2_plan_executor.api.deps.transport import TransportDeps
from rmf2_plan_executor.transport.serializer import decode_plan, encode_dataclass

router = APIRouter(prefix="/plans", tags=["plans"])


class PlanInjectResponse(BaseModel):
    status: str
    robot_id: str


@router.post("/{robot_id}")
def inject_plan(robot_id: str, body: dict, transport: TransportDeps) -> PlanInjectResponse:
    """Inject a plan directly for a robot, bypassing the plan server AMQP path.

    The request body must be a serialised Plan object matching the res_mapf Plan JSON schema.
    """
    try:
        plan = decode_plan(json.dumps(body))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid plan body: {exc}") from exc
    transport._publish(f"res/plan/{robot_id}", encode_dataclass(plan))
    return PlanInjectResponse(status="published", robot_id=robot_id)
