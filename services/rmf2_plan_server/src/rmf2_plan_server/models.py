from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class InfoResponse(BaseModel):
    service_version: str
    api_version: str


class RobotOnboardRequest(BaseModel):
    robot_id: str
    start_location: str


class RobotOnboardResponse(BaseModel):
    robot_id: str
    start_location: str
    status: str


class TaskRequest(BaseModel):
    task_id: str
    robot_id: str
    goal: str


class TaskResponse(BaseModel):
    task_id: str
    robot_id: str
    goal: str
    status: str


class ParticipantsRequest(BaseModel):
    participants: list[str]


class ParticipantsResponse(BaseModel):
    participants: list[str]
    status: str
