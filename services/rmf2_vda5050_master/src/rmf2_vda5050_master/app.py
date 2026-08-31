"""VDA5050 master service — FastAPI app."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .config import _MODE, settings
from .logger import setup_logging
from .master import make_master


config = settings()

# disable docs for prod
_docs_url = None if _MODE == "prod" else "/docs"
_redoc_url = None if _MODE == "prod" else "/redoc"

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    with make_master(config) as master:
        app.state.master = master
        yield


app = FastAPI(lifespan=lifespan, docs_url=_docs_url, redoc_url=_redoc_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
