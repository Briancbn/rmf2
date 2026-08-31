from fastapi import APIRouter

from .endpoints import agvs, connections, instant_actions, states

api_router = APIRouter()
api_router.include_router(agvs.router, prefix="/agvs", tags=["agvs"])
api_router.include_router(states.router, prefix="/states", tags=["states"])
api_router.include_router(connections.router, prefix="/connections", tags=["connections"])
api_router.include_router(instant_actions.router, prefix="/instant_actions", tags=["instant_actions"])
