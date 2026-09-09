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
    status: str
    robot_id: str
