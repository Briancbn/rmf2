from fastapi import APIRouter

from res_plan_server.transport.transport_messages import ParticipantDiscoveryMsg

from rmf2_plan_server.api.deps.transport import TransportDeps
from rmf2_plan_server.models import ParticipantsRequest, ParticipantsResponse

router = APIRouter()


@router.post("")
async def publish_participants(body: ParticipantsRequest, transport: TransportDeps) -> ParticipantsResponse:
    transport.publish_participant_discovery(ParticipantDiscoveryMsg(participants=body.participants))
    return ParticipantsResponse(participants=body.participants, status="published")
