from fastapi import APIRouter

from rmf2_plan_server.models import HealthResponse

router = APIRouter()


@router.get("")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
