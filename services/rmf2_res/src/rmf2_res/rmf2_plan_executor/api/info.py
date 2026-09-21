from importlib.metadata import version as pkg_version

from fastapi import APIRouter

from rmf2_res.models import InfoResponse

router = APIRouter()


@router.get("")
async def info() -> InfoResponse:
    return InfoResponse(
        service_version=pkg_version("rmf2-res"),
        api_version="v1",
    )
