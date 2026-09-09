from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import datetime

from res_plan_server.transport.transport_messages import (
    CommittedLocationMsg,
    CommittedLocationsResponseMsg,
    PlanErrorMsg,
    PlanIdMsg,
    PlanProgressMsg,
    ParticipantDiscoveryMsg,
    RobotOnboardMsg,
    TaskRequestMsg,
)


class _Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def encode_dataclass(obj) -> str:
    return json.dumps(dataclasses.asdict(obj), cls=_Encoder)


def decode_robot_onboard(s: str) -> RobotOnboardMsg:
    d = json.loads(s)
    return RobotOnboardMsg(robot_id=d["robot_id"], start_location=d["start_location"])


def decode_participant_discovery(s: str) -> ParticipantDiscoveryMsg:
    d = json.loads(s)
    return ParticipantDiscoveryMsg(participants=d["participants"])


def decode_task_request(s: str) -> TaskRequestMsg:
    d = json.loads(s)
    return TaskRequestMsg(task_id=d["task_id"], robot_id=d["robot_id"], goal=d["goal"])


def decode_committed_locations_response(s: str) -> CommittedLocationsResponseMsg:
    d = json.loads(s)
    committed = [
        CommittedLocationMsg(
            robot_id=c["robot_id"],
            location=c["location"],
            waypoint_index=c["waypoint_index"],
            progress=c["progress"],
            task_id=c["task_id"],
        )
        for c in d.get("committed_locations", [])
    ]
    return CommittedLocationsResponseMsg(
        request_id=d["request_id"],
        committed_locations=committed,
        stationary_agents=d.get("stationary_agents", []),
    )


def _decode_plan_id_msg(d: dict) -> PlanIdMsg:
    return PlanIdMsg(destination_uuid=d["destination_uuid"], plan_version=d["plan_version"])


def decode_plan_progress(s: str) -> PlanProgressMsg:
    d = json.loads(s)
    return PlanProgressMsg(
        plan_id=_decode_plan_id_msg(d["plan_id"]),
        reached_waypoint=d["reached_waypoint"],
        target_waypoint=d["target_waypoint"],
    )


def decode_plan_error(s: str) -> PlanErrorMsg:
    d = json.loads(s)
    return PlanErrorMsg(
        plan_id=_decode_plan_id_msg(d["plan_id"]),
        error_code=d["error_code"],
        details=d["details"],
    )
