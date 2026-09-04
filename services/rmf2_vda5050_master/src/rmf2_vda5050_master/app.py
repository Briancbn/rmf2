"""VDA5050 master service — FastAPI app."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .config import _MODE, settings
from .database import init_db
from .db_models import AgvRecord  # noqa: F401 — registers table with Base
from .logger import setup_logging
from .master import make_master
from .transport import (
    Heartbeat,
    MultiThreadedExecutor,
    ServerTransportAmqp,
    ServerTransportZenoh,
    TransportManager,
)

config = settings()

# disable docs for prod
_docs_url = None if _MODE == "prod" else "/docs"
_redoc_url = None if _MODE == "prod" else "/redoc"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    app.state.layout_result = None

    transport_manager = TransportManager(topic_prefix="rmf2_vda5050_master/v1")
    if config.amqp.enabled:
        transport_manager.add_transport(
            "amqp", ServerTransportAmqp.from_url(config.amqp.url, config.amqp.exchange)
        )
    if config.zenoh.enabled:
        transport_manager.add_transport(
            "zenoh",
            ServerTransportZenoh.from_endpoints(config.zenoh.endpoints)
            if config.zenoh.endpoints
            else ServerTransportZenoh(),
        )

    transport_executor = MultiThreadedExecutor(transport_manager)
    transport_executor.start()

    app.state.transport = transport_manager

    heartbeat = Heartbeat(config.heartbeat_interval)

    with init_db(config.database_url) as session_factory:
        app.state.session_factory = session_factory
        with make_master(
            config, session_factory, transport_manager, heartbeat=heartbeat
        ) as master:
            app.state.master = master
            heartbeat.start()
            yield
            heartbeat.stop()

    transport_executor.stop()


app = FastAPI(lifespan=lifespan, docs_url=_docs_url, redoc_url=_redoc_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/v1")
