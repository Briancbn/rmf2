from fastapi import APIRouter

from .endpoints import states, instant_actions

api_router = APIRouter()
api_router.include_router(states.router, prefix="/states", tags=["states"])
api_router.include_router(instant_actions.router, prefix="/instant_actions", tags=["instant_actions"])
