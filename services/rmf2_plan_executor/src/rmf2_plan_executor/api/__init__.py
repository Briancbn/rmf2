from fastapi import APIRouter

from . import health, info
from .v1 import v1_router

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(info.router, prefix="/info", tags=["info"])
api_router.include_router(v1_router)
