from pydantic import BaseModel
from res_plan_server.transport.transport_messages import RobotOnboardMsg


class RobotOnboardRequest(BaseModel):
    robot_id: str
    start_location: str


class RobotOnboardResponse(BaseModel):
    status: str
    robot_id: str


class AgvInitConfig(BaseModel):
    x: float | None = None
    y: float | None = None
    theta: float | None = None
    last_node_id: str | None = None
    map_id: str | None = None


class AgvConfig(BaseModel):
    """Mirrors vda5050_master's/rmf2_plan_server's `[[agvs]]` config.toml table, so the same
    file can onboard robots here via the `agvs` alias for `robots`."""

    manufacturer: str
    serial_number: str
    init_config: AgvInitConfig | None = None

    def to_robot_onboard_msg(self) -> RobotOnboardMsg:
        return RobotOnboardMsg(
            robot_id=f"{self.manufacturer}/{self.serial_number}",
            start_location=(self.init_config.last_node_id if self.init_config else None) or "",
        )
