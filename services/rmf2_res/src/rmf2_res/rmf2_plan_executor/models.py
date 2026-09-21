from pydantic import BaseModel


class RobotOnboardRequest(BaseModel):
    robot_id: str
    start_location: str


class RobotOnboardResponse(BaseModel):
    status: str
    robot_id: str
