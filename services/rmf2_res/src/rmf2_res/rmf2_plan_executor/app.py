"""RMF2 Plan Executor service — FastAPI app."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rmf2_res.database import init_db
from rmf2_res.db_models import RobotRecord  # noqa: F401 — registers table with Base
from rmf2_res.rmf2_plan_executor.api import api_router
from rmf2_res.rmf2_plan_executor.config import _MODE, settings
from rmf2_res.logger import setup_logging
from rmf2_res.rmf2_plan_executor.plan_executor import make_plan_executor

setup_logging()

config = settings()

_docs_url = None if _MODE == "prod" else "/docs"
_redoc_url = None if _MODE == "prod" else "/redoc"


@asynccontextmanager
async def lifespan(app: FastAPI):
    with init_db(config.database_url) as session_factory:
        app.state.session_factory = session_factory
        with make_plan_executor(config, session_factory) as ctx:
            app.state.context = ctx
            yield


app = FastAPI(
    title="RMF2 Plan Executor",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    root_path=config.root_path,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
