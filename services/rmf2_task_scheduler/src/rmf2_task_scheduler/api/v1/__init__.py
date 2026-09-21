from fastapi import APIRouter

from .endpoints import processes, schedule, series, tasks

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(schedule.router, prefix="/schedule", tags=["schedule"])
v1_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
v1_router.include_router(processes.router, prefix="/processes", tags=["processes"])
v1_router.include_router(series.router, prefix="/series", tags=["series"])
