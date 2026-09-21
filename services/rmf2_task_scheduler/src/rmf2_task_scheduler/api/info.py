from importlib.metadata import version as pkg_version

from fastapi import APIRouter

from rmf2_task_scheduler.models import InfoResponse

router = APIRouter()


@router.get("")
async def info() -> InfoResponse:
    return InfoResponse(
        service_version=pkg_version("rmf2-task-scheduler"),
        api_version="v1",
    )
