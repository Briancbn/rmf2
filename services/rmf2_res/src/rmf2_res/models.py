import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
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


class CommittedLocationStatus(BaseModel):
    robot_id: str
    location: str
    waypoint_index: int
    progress: float
    task_id: str


class CommittedLocationsRecordStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    request_id: str
    committed_locations: list[CommittedLocationStatus] = Field(validation_alias="committed_locations_json")
    stationary_agents: list[str] = Field(validation_alias="stationary_agents_json")
    updated_at: datetime

    @field_validator("committed_locations", "stationary_agents", mode="before")
    @classmethod
    def _parse_json(cls, value: str | list) -> list:
        return json.loads(value) if isinstance(value, str) else value


class LifSummary(BaseModel):
    layout_ids: list[str]
    project_identification: str | None = None
    creator: str | None = None
    export_timestamp: str | None = None
    lif_version: str | None = None
    loaded_at: datetime
