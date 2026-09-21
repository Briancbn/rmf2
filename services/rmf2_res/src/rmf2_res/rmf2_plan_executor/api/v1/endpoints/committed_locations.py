from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from rmf2_res import crud
from rmf2_res.models import CommittedLocationsRecordStatus
from rmf2_res.rmf2_plan_executor.api.deps.db import DbSession
from rmf2_res.rmf2_plan_executor.api.deps.transport import TransportDeps

router = APIRouter(prefix="/committed_locations", tags=["committed_locations"])


class CommittedLocationsRequestResponse(BaseModel):
    status: str
    request_id: str


@router.get("", response_model_exclude_none=True)
def get_committed_locations_requests(db: DbSession, skip: int = 0, limit: int = 100) -> list[CommittedLocationsRecordStatus]:
    records = crud.committed_locations_record.get_multi(db, skip=skip, limit=limit)
    return [CommittedLocationsRecordStatus.model_validate(record) for record in records]


@router.get("/{request_id}", response_model_exclude_none=True)
def get_committed_locations_request(request_id: str, db: DbSession) -> CommittedLocationsRecordStatus:
    record = crud.committed_locations_record.get(db, request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Committed locations request not found")
    return CommittedLocationsRecordStatus.model_validate(record)


@router.post("/request")
def request_committed_locations(transport: TransportDeps) -> CommittedLocationsRequestResponse:
    """Trigger a committed-locations request, equivalent to the AMQP committed_locations/request message."""
    request_id = str(uuid4())
    transport.request_committed_locations(request_id)
    return CommittedLocationsRequestResponse(status="published", request_id=request_id)
