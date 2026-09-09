"""RMF2 Plan Server — FastAPI app."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rmf2_plan_server.api import api_router
from rmf2_plan_server.config import _MODE, settings
from rmf2_plan_server.logger import setup_logging
from rmf2_plan_server.transport.amqp import AmqpServerTransport

config = settings()

_docs_url = None if _MODE == "prod" else "/docs"
_redoc_url = None if _MODE == "prod" else "/redoc"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()

    transport = AmqpServerTransport(config.amqp.url, config.amqp.exchange)
    transport.start()
    app.state.transport = transport

    plan_server = None
    if config.map_path is not None:
        from res_map import lif_parser
        from res_map.grid.grid_utils import infer_obstacles, snap_to_grid
        from res_mapf_planning.mapf_solve.solvers.cbs_adapter import CBSAdapter
        from res_mapf_planning.planning.mapf_coordinator import MAPFCoordinator
        from res_mapf_planning.planning.multi_agent_context import MultiAgentContext
        from res_mapf_planning.traffic_dependencies.plan_generator import PlanGenerator
        from res_plan_server.plan_server import PlanServer

        map_data = lif_parser.load_lif(config.map_path)
        grid_map = snap_to_grid(map_data)
        grid_map.obstacles = infer_obstacles(map_data, grid_map)

        context = MultiAgentContext()
        solver = CBSAdapter(grid_map)
        coordinator = MAPFCoordinator(context, solver)
        plan_generator = PlanGenerator()

        plan_server = PlanServer(
            transport=transport,
            context=context,
            coordinator=coordinator,
            plan_generator=plan_generator,
        )
        plan_server.start()

    app.state.plan_server = plan_server

    yield

    if plan_server is not None:
        plan_server.stop()
    transport.stop()


app = FastAPI(lifespan=lifespan, docs_url=_docs_url, redoc_url=_redoc_url, root_path=config.root_path)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
