from fastapi import APIRouter
from pydantic import BaseModel

from res_plan_server.transport.transport_messages import ParticipantDiscoveryMsg

from rmf2_res.rmf2_plan_executor.api.deps.transport import TransportDeps

router = APIRouter(prefix="/participants", tags=["participants"])


class ParticipantDiscoveryRequest(BaseModel):
    participants: list[str]


class ParticipantDiscoveryResponse(BaseModel):
    status: str
    participants: list[str]


@router.post("")
def discover_participants(
    body: ParticipantDiscoveryRequest, transport: TransportDeps
) -> ParticipantDiscoveryResponse:
    msg = ParticipantDiscoveryMsg(participants=body.participants)
    transport.discover_participants(msg)
    return ParticipantDiscoveryResponse(status="published", participants=body.participants)
