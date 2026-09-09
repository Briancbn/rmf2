from fastapi import APIRouter

from rmf2_plan_executor.api.v1.endpoints import committed_locations, participants, plans, robots

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(robots.router)
v1_router.include_router(participants.router)
v1_router.include_router(plans.router)
v1_router.include_router(committed_locations.router)
