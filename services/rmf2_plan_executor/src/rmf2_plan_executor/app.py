"""RMF2 Plan Executor service — FastAPI app."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from res_map import lif_parser
from res_map.map_data import MapData
from res_plan_execution.plan_execution.dependency_manager import DependencyManager
from res_plan_execution.plan_execution.plan_executor import PlanExecutor

from rmf2_plan_executor.api import api_router
from rmf2_plan_executor.config import _MODE, settings
from rmf2_plan_executor.logger import setup_logging
from rmf2_plan_executor.robot_controller import Vda5050RobotController
from rmf2_plan_executor.transport.amqp import AmqpExecutorTransport

config = settings()

_docs_url = None if _MODE == "prod" else "/docs"
_redoc_url = None if _MODE == "prod" else "/redoc"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()

    map_data = lif_parser.load_lif(config.map_path) if config.map_path else MapData(world_positions={}, world_position_to_name={}, edges=[])

    agent_map = {
        a.agent_id: {"manufacturer": a.manufacturer, "serial_number": a.serial_number}
        for a in config.agents
    }

    transport = AmqpExecutorTransport(url=config.amqp.url, exchange=config.amqp.exchange)
    robot_controller = Vda5050RobotController(
        map_data=map_data,
        amqp_url=config.amqp.url,
        amqp_exchange=config.amqp.exchange,
        agent_map=agent_map,
        lif_path=config.map_path,
    )
    executor = PlanExecutor(transport=transport, robot_controller=robot_controller, dependency_manager=DependencyManager())

    app.state.transport = transport
    app.state.executor = executor
    app.state.robot_controller = robot_controller

    transport.start()
    robot_controller.start()
    executor.start()

    yield

    executor.stop()
    robot_controller.shutdown()
    transport.stop()


app = FastAPI(lifespan=lifespan, docs_url=_docs_url, redoc_url=_redoc_url, root_path=config.root_path)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
