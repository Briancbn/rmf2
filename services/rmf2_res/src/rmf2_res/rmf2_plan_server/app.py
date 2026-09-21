"""RMF2 Plan Server — FastAPI app."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rmf2_res.database import init_db
from rmf2_res.db_models import RobotRecord  # noqa: F401 — registers table with Base
from rmf2_res.logger import setup_logging
from rmf2_res.rmf2_plan_server.api import api_router
from rmf2_res.rmf2_plan_server.config import _MODE, settings
from rmf2_res.rmf2_plan_server.plan_server import make_plan_server
from rmf2_res.transport import ServerTransportAmqp, ServerTransportBase

config = settings()

_docs_url = None if _MODE == "prod" else "/docs"
_redoc_url = None if _MODE == "prod" else "/redoc"

def _build_transport() -> ServerTransportBase | None:
    if config.transport is None:
        return None
    if config.transport == "amqp":
        return ServerTransportAmqp.from_url(config.amqp.url, config.amqp.exchange)
    raise ValueError(f"Unknown transport: {config.transport!r}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()

    transport = _build_transport()

    with init_db(config.database_url) as session_factory:
        app.state.session_factory = session_factory
        with make_plan_server(config, transport, session_factory) as ctx:
            app.state.context = ctx
            yield


app = FastAPI(
    title="RMF2 Plan Server",
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
