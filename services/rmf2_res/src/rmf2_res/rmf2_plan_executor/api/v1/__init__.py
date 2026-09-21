from fastapi import APIRouter

from rmf2_res.rmf2_plan_executor.api.v1.endpoints import (
    committed_locations,
    layout,
    participants,
    plans,
    robots,
    tasks,
)

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(robots.router)
v1_router.include_router(tasks.router)
v1_router.include_router(layout.router)
v1_router.include_router(participants.router)
v1_router.include_router(plans.router)
v1_router.include_router(committed_locations.router)
