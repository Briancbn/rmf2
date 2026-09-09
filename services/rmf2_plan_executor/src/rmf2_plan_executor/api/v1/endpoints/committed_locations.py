import json
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

from rmf2_plan_executor.api.deps.transport import TransportDeps

router = APIRouter(prefix="/committed_locations", tags=["committed_locations"])


class CommittedLocationsRequestResponse(BaseModel):
    status: str
    request_id: str


@router.post("/request")
def request_committed_locations(transport: TransportDeps) -> CommittedLocationsRequestResponse:
    """Trigger a committed-locations request, equivalent to the AMQP res/committed_locations_request message."""
    request_id = str(uuid4())
    transport._publish("res/committed_locations_request", json.dumps({"request_id": request_id}))
    return CommittedLocationsRequestResponse(status="published", request_id=request_id)
