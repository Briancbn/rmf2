from fastapi import APIRouter

from rmf2_plan_executor.api.deps.transport import TransportDeps
from rmf2_plan_executor.models import RobotOnboardRequest, RobotOnboardResponse
from rmf2_plan_executor.transport.serializer import encode_dataclass
from res_plan_server.transport.transport_messages import RobotOnboardMsg

router = APIRouter(prefix="/robots", tags=["robots"])


@router.post("")
def onboard_robot(body: RobotOnboardRequest, transport: TransportDeps) -> RobotOnboardResponse:
    msg = RobotOnboardMsg(robot_id=body.robot_id, start_location=body.start_location)
    transport._publish("res/robot_onboard", encode_dataclass(msg))
    return RobotOnboardResponse(status="onboarding", robot_id=body.robot_id)
