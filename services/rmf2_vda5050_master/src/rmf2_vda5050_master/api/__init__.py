from fastapi import APIRouter

from .endpoints import (
    agvs,
    connections,
    factsheets,
    instant_actions,
    layout,
    orders,
    states,
    visualization,
)

api_router = APIRouter()
api_router.include_router(layout.router, prefix="/layout", tags=["layout"])
api_router.include_router(agvs.router, prefix="/agvs", tags=["agvs"])
api_router.include_router(
    connections.router, prefix="/connections", tags=["connections"]
)
api_router.include_router(factsheets.router, prefix="/factsheets", tags=["factsheets"])
api_router.include_router(states.router, prefix="/states", tags=["states"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])
api_router.include_router(
    instant_actions.router, prefix="/instant_actions", tags=["instant_actions"]
)
api_router.include_router(
    visualization.router, prefix="/visualizations", tags=["visualizations"]
)
