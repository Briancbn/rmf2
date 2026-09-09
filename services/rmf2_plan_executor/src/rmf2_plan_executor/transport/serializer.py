from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import datetime
from typing import Optional
from uuid import UUID

from res_mapf_planning.traffic_dependencies.models.plan import Plan
from res_mapf_planning.traffic_dependencies.models.plan_id import PlanId
from res_mapf_planning.traffic_dependencies.models.waypoint import Waypoint
from res_mapf_planning.traffic_dependencies.models.traffic_dependency import TrafficDependency
from res_plan_server.transport.transport_messages import (
    CommittedLocationsResponseMsg,
    PlanErrorMsg,
    PlanIdMsg,
    PlanProgressMsg,
    RobotOnboardMsg,
    ParticipantDiscoveryMsg,
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


def decode_plan(s: str) -> Plan:
    d = json.loads(s)
    plan_id: Optional[PlanId] = None
    if d.get("plan_id"):
        pid = d["plan_id"]
        plan_id = PlanId(destination_session=UUID(pid["destination_session"]), plan_version=pid["plan_version"])

    waypoints = []
    for w in d.get("waypoints", []):
        blockers = []
        for b in w.get("departure_blockers", []):
            bpid = b["plan_id"]
            blockers.append(TrafficDependency(
                name=b["name"],
                plan_id=PlanId(destination_session=UUID(bpid["destination_session"]), plan_version=bpid["plan_version"]),
                required_progress=b["required_progress"],
            ))
        waypoints.append(Waypoint(
            name=w["name"],
            position=tuple(w["position"]),
            progress=w["progress"],
            departure_action=w.get("departure_action", ""),
            departure_blockers=blockers,
        ))

    return Plan(
        waypoints=waypoints,
        plan_id=plan_id,
        workflow=d.get("workflow", ""),
        map_name=d.get("map_name", ""),
    )


def decode_committed_locations_request(s: str) -> str:
    d = json.loads(s)
    return d["request_id"]
