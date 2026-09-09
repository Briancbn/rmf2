from fastapi import APIRouter

from rmf2_plan_server.api.v1.endpoints import participants, robots, tasks

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(robots.router, prefix="/robots", tags=["robots"])
v1_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
v1_router.include_router(participants.router, prefix="/participants", tags=["participants"])
