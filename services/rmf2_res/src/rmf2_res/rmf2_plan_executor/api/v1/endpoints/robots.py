from fastapi import APIRouter, HTTPException

from rmf2_res import crud
from rmf2_res.models import RobotStatus
from rmf2_res.rmf2_plan_executor.api.deps.db import DbSession
from rmf2_res.rmf2_plan_executor.api.deps.transport import TransportDeps
from rmf2_res.rmf2_plan_executor.models import RobotOnboardRequest, RobotOnboardResponse
from res_plan_server.transport.transport_messages import RobotOnboardMsg

router = APIRouter(prefix="/robots", tags=["robots"])


@router.get("")
def get_onboarded_robots(db: DbSession, skip: int = 0, limit: int = 100) -> list[RobotStatus]:
    records = crud.robot_record.get_multi_from_attr(db, {"is_onboarded": True}, skip=skip, limit=limit)
    return [RobotStatus.model_validate(record) for record in records]


def _get_robot_status(db: DbSession, robot_id: str) -> RobotStatus:
    record = crud.robot_record.get(db, robot_id)
    if record is None or not record.is_onboarded:
        raise HTTPException(status_code=404, detail="Robot not onboarded")
    return RobotStatus.model_validate(record)


@router.get("/{manufacturer}/{serial_number}")
def get_robot_by_manufacturer_serial(manufacturer: str, serial_number: str, db: DbSession) -> RobotStatus:
    return _get_robot_status(db, f"{manufacturer}/{serial_number}")


@router.get("/{robot_id}")
def get_robot(robot_id: str, db: DbSession) -> RobotStatus:
    return _get_robot_status(db, robot_id)


@router.post("")
def onboard_robot(body: RobotOnboardRequest, transport: TransportDeps) -> RobotOnboardResponse:
    msg = RobotOnboardMsg(robot_id=body.robot_id, start_location=body.start_location)
    transport.onboard_robot(msg)
    return RobotOnboardResponse(status="onboarding", robot_id=body.robot_id)
