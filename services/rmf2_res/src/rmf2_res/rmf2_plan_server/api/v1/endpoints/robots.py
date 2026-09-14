from fastapi import APIRouter, HTTPException

from res_plan_server.transport.transport_messages import RobotOnboardMsg

from rmf2_res import crud
from rmf2_res.models import RobotOnboardBatchResponse, RobotStatus
from rmf2_res.rmf2_plan_server.api.deps.context import ContextDeps
from rmf2_res.rmf2_plan_server.api.deps.db import DbSession
from rmf2_res.rmf2_plan_server.plan_server import save_robot

router = APIRouter()


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
async def onboard_robots(
    robots: list[RobotOnboardMsg], context: ContextDeps, db: DbSession
) -> RobotOnboardBatchResponse:
    skipped_already_onboarded: list[RobotOnboardMsg] = []
    to_onboard: list[RobotOnboardMsg] = []
    for robot in robots:
        record = crud.robot_record.get(db, robot.robot_id)
        if record is not None and record.is_onboarded:
            skipped_already_onboarded.append(robot)
        else:
            to_onboard.append(robot)

    result = context.transport.onboard_robot_batch(to_onboard)
    for robot in result.onboarded:
        save_robot(db, robot.robot_id, robot.start_location)

    return RobotOnboardBatchResponse(
        onboarded=result.onboarded,
        failed=result.failed,
        skipped_already_onboarded=skipped_already_onboarded,
    )
