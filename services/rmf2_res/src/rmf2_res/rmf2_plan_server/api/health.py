from fastapi import APIRouter

from rmf2_res.models import HealthResponse

router = APIRouter()


@router.get("")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
