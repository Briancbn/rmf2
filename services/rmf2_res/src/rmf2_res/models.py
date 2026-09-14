from datetime import datetime

from pydantic import BaseModel, ConfigDict
from res_mapf_planning.traffic_dependencies.models.plan import Plan
from res_plan_server.transport.transport_messages import RobotOnboardMsg


class HealthResponse(BaseModel):
    status: str


class InfoResponse(BaseModel):
    service_version: str
    api_version: str


class RobotOnboardResponse(BaseModel):
    decision: str
    errors: list[str]


class RobotOnboardBatchResponse(BaseModel):
    onboarded: list[RobotOnboardMsg]
    failed: list[RobotOnboardMsg]
    skipped_already_onboarded: list[RobotOnboardMsg]


class RobotStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    robot_id: str
    start_location: str
    is_onboarded: bool
    onboarded_at: datetime | None = None


class TaskSubmitResponse(BaseModel):
    decision: str
    errors: list[str]
    plans: list[Plan]


class TaskRecordStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: str
    robot_id: str
    status: str
    source: str
    reason: str | None = None
    superseded_by: str | None = None
    updated_at: datetime


class PlanCacheEntry(BaseModel):
    problem: list[dict[str, str]]
    plans: dict[str, Plan]


class PlanRecordStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plan_id: str
    robot_id: str
    status: str
    reached_waypoint: int | None = None
    target_waypoint: int | None = None
    reason: str | None = None
    updated_at: datetime
