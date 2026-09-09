from fastapi import APIRouter

from res_plan_server.transport.transport_messages import RobotOnboardMsg

from rmf2_plan_server.api.deps.transport import TransportDeps
from rmf2_plan_server.models import RobotOnboardRequest, RobotOnboardResponse

router = APIRouter()


@router.post("")
async def onboard_robot(body: RobotOnboardRequest, transport: TransportDeps) -> RobotOnboardResponse:
    transport.publish_robot_onboard(RobotOnboardMsg(robot_id=body.robot_id, start_location=body.start_location))
    return RobotOnboardResponse(robot_id=body.robot_id, start_location=body.start_location, status="onboarding")
