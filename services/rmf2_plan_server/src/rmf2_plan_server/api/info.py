from importlib.metadata import version as pkg_version

from fastapi import APIRouter

from rmf2_plan_server.models import InfoResponse

router = APIRouter()


@router.get("")
async def info() -> InfoResponse:
    return InfoResponse(
        service_version=pkg_version("rmf2-plan-server"),
        api_version="v1",
    )
