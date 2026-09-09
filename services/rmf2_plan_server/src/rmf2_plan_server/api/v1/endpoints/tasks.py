from fastapi import APIRouter

from res_plan_server.transport.transport_messages import TaskRequestMsg

from rmf2_plan_server.api.deps.transport import TransportDeps
from rmf2_plan_server.models import TaskRequest, TaskResponse

router = APIRouter()


@router.post("")
async def submit_task(body: TaskRequest, transport: TransportDeps) -> TaskResponse:
    transport.publish_task_request(body.robot_id, TaskRequestMsg(task_id=body.task_id, robot_id=body.robot_id, goal=body.goal))
    return TaskResponse(task_id=body.task_id, robot_id=body.robot_id, goal=body.goal, status="submitted")
