"""RMF2 Plan Server — context manager for plan server lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from res_map import lif_parser
from res_map.grid.grid_utils import infer_obstacles, snap_to_grid
from res_mapf_planning.mapf_solve.solvers.cbs_adapter import CBSAdapter
from res_mapf_planning.planning.mapf_coordinator import MAPFCoordinator
from res_mapf_planning.planning.multi_agent_context import MultiAgentContext
from res_mapf_planning.traffic_dependencies.models.plan import Plan
from res_mapf_planning.traffic_dependencies.plan_generator import PlanGenerator
from res_plan_server.plan_server import PlanServer as RESPlanServer
from res_plan_server.task_status import TaskStatusUpdate
from res_plan_server.transport.server_base_transport import ServerBaseTransport as RESPlanServerTransportBase
from res_plan_server.transport.transport_messages import (
    CommittedLocationsResponseMsg,
    ParticipantDiscoveryMsg,
    PlanErrorMsg,
    PlanProgressMsg,
    RobotOnboardMsg,
    TaskRequestMsg,
)

from rmf2_res import crud
from rmf2_res.logger import get_logger
from rmf2_res.models import RobotOnboardBatchResponse, RobotOnboardResponse
from rmf2_res.transport import PublisherBase, ServerTransportBase, SubscriberBase, WrappedCallback
from rmf2_res.rmf2_plan_server.config import Settings

LOGGER = get_logger(__name__)


class RESPlanServerTransport(RESPlanServerTransportBase):
    """ServerBaseTransport implementation that maps the plan server's typed pub/sub
    onto a generic :class:`ServerTransportBase`, and stores the robot-onboarding
    callback for direct invocation at startup.

    With ``transport=None`` the observer stays inert: subscriptions and publishes are
    dropped with a warning, so the service can run without a broker.
    """

    def __init__(
        self,
        transport: ServerTransportBase | None = None,
        plan_server_topic_prefix: str | None = None,
        plan_executor_topic_prefix: str | None = None,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._transport = transport
        self._plan_server_topic_prefix = plan_server_topic_prefix
        self._plan_executor_topic_prefix = plan_executor_topic_prefix
        self._session_factory = session_factory
        self._subscribers: list[SubscriberBase] = []
        self._publishers: dict[str, PublisherBase] = {}

        # capture callbacks to expose — "robot_onboard" and "participant_discovery"
        # for the fixed subscriptions, f"task_request:{robot_id}" per onboarded robot
        self._callbacks: dict[str, WrappedCallback] = {}

    def _full_plan_server(self, topic: str) -> str:
        return f"{self._plan_server_topic_prefix}/{topic}" if self._plan_server_topic_prefix else topic

    def _full_plan_executor(self, topic: str) -> str:
        return f"{self._plan_executor_topic_prefix}/{topic}" if self._plan_executor_topic_prefix else topic

    def _add_subscriber(self, message_type: type, topic: str, callback: Callable) -> None:
        if self._transport is None:
            LOGGER.warning("No transport — dropping subscription to '%s'", topic)
            return
        self._subscribers.append(
            self._transport.create_subscriber(message_type, topic, callback)
        )

    def _add_plan_server_subscriber(self, message_type: type, topic: str, callback: Callable) -> None:
        return self._add_subscriber(message_type, self._full_plan_server(topic), callback)

    def _add_plan_executor_subscriber(self, message_type: type, topic: str, callback: Callable) -> None:
        return self._add_subscriber(message_type, self._full_plan_executor(topic), callback)

    def _publish(self, message_type: type, topic: str, message: Any) -> None:
        if self._transport is None:
            LOGGER.warning("No transport — dropping publish to '%s'", topic)
            return
        publisher = self._publishers.get(topic)
        if publisher is None:
            publisher = self._transport.create_publisher(message_type, topic)
            self._publishers[topic] = publisher
        publisher.publish(message)

    def _publish_plan_server(self, message_type: type, topic: str, message: Any) -> None:
        return self._publish(message_type, self._full_plan_server(topic), message)

    def _publish_plan_executor(self, message_type: type, topic: str, message: Any) -> None:
        return self._publish(message_type, self._full_plan_executor(topic), message)


    # ------------------------------------------------------------------ #
    # Exposed Callbacks                                                  #
    # ------------------------------------------------------------------ #

    def onboard_robot(self, robot: RobotOnboardMsg) -> RobotOnboardResponse:
        callback = self._callbacks.get("robot_onboard")
        if callback is None:
            LOGGER.warning("Plan Server is not initialized!")
            return RobotOnboardResponse(
                decision="REJECTED", errors=["Plan Server is not initialized!"]
            )
        try:
            callback(robot)
        except Exception as exc:  # noqa: BLE001 — surface as a rejection, not a crash
            LOGGER.error("Failed to onboard robot %s: %s", robot.robot_id, exc)
            return RobotOnboardResponse(decision="REJECTED", errors=[str(exc)])
        return RobotOnboardResponse(decision="ACCEPTED", errors=[])

    def onboard_robot_batch(self, robots: list[RobotOnboardMsg]) -> RobotOnboardBatchResponse:
        onboarded: list[RobotOnboardMsg] = []
        failed: list[RobotOnboardMsg] = []
        for robot in robots:
            result = self.onboard_robot(robot)
            (onboarded if result.decision == "ACCEPTED" else failed).append(robot)
        return RobotOnboardBatchResponse(onboarded=onboarded, failed=failed, skipped_already_onboarded=[])

    def submit_task(self, task: TaskRequestMsg) -> None:
        if "robot_onboard" not in self._callbacks:
            LOGGER.warning("Plan Server is not initialized!")
            return None
        on_task_request = self._callbacks.get(f"task_request:{task.robot_id}")
        if on_task_request is None:
            LOGGER.warning("robot is not initialized!")
            return None

        on_task_request(task)
        return None

    # ------------------------------------------------------------------ #
    # Subscriptions                                                      #
    # ------------------------------------------------------------------ #

    def subscribe_robot_onboarding(self, callback: Callable[[RobotOnboardMsg], None]) -> None:
        wrapped_callback = WrappedCallback(callback)
        self._callbacks["robot_onboard"] = wrapped_callback
        self._add_plan_server_subscriber(RobotOnboardMsg, "robot_onboard", wrapped_callback)

    def subscribe_participant_discovery(self, callback: Callable[[ParticipantDiscoveryMsg], None]) -> None:
        wrapped_callback = WrappedCallback(callback)
        self._callbacks["participant_discovery"] = wrapped_callback
        self._add_plan_server_subscriber(ParticipantDiscoveryMsg, "destination/discovery", wrapped_callback)

    def subscribe_task_request(self, robot_id: str, callback: Callable[[TaskRequestMsg], None]) -> None:
        wrapped_callback = WrappedCallback(callback)
        self._callbacks[f"task_request:{robot_id}"] = wrapped_callback
        self._add_plan_server_subscriber(TaskRequestMsg, f"{robot_id}/task_request", wrapped_callback)

    def subscribe_committed_locations_response(self, callback: Callable[[CommittedLocationsResponseMsg], None]) -> None:
        self._add_plan_executor_subscriber(
            CommittedLocationsResponseMsg, "committed_locations/response", WrappedCallback(callback)
        )

    def subscribe_plan_progress(self, robot_id: str, callback: Callable[[PlanProgressMsg], None]) -> None:
        def post_plan_progress(message: PlanProgressMsg) -> None:
            if self._session_factory is not None:
                with self._session_factory() as session:
                    save_plan_progress(session, robot_id, message)

        self._add_plan_executor_subscriber(
            PlanProgressMsg, f"{robot_id}/plan/progress", WrappedCallback(callback, post=post_plan_progress)
        )

    def subscribe_plan_error(self, robot_id: str, callback: Callable[[PlanErrorMsg], None]) -> None:
        def post_plan_error(message: PlanErrorMsg) -> None:
            if self._session_factory is not None:
                with self._session_factory() as session:
                    save_plan_error(session, robot_id, message)

        self._add_plan_executor_subscriber(
            PlanErrorMsg, f"{robot_id}/plan/error", WrappedCallback(callback, post=post_plan_error)
        )

    # ------------------------------------------------------------------ #
    # Publishes                                                          #
    # ------------------------------------------------------------------ #

    def publish_plan(self, robot_id: str, plan: Plan) -> None:
        self._publish_plan_executor(Plan, f"{robot_id}/plan", plan)

    def publish_committed_locations_request(self, request_id: str) -> None:
        self._publish_plan_executor(dict, "committed_locations/request", {"request_id": request_id})

    def publish_task_status(self, update: TaskStatusUpdate) -> None:
        self._publish_plan_server(TaskStatusUpdate, "fleet/task_status", update)
        if self._session_factory is not None:
            with self._session_factory() as session:
                save_task_status(session, update)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """No-op — the wrapped transport owns its connection and starts itself."""

    def stop(self) -> None:
        """Release every subscription. Disconnecting the transport is the caller's job."""
        self._subscribers.clear()


def save_robot(db: Session, robot_id: str, start_location: str) -> None:
    onboarded_at = datetime.now(timezone.utc)
    if crud.robot_record.get(db, robot_id) is None:
        crud.robot_record.create(
            db, robot_id, start_location=start_location, is_onboarded=True, onboarded_at=onboarded_at
        )
    else:
        crud.robot_record.update(
            db, robot_id, start_location=start_location, is_onboarded=True, onboarded_at=onboarded_at
        )


def save_task_status(db: Session, update: TaskStatusUpdate) -> None:
    fields = dict(
        robot_id=update.robot_id,
        status=update.status.name,
        source=update.source,
        reason=update.reason,
        superseded_by=update.superseded_by,
        updated_at=update.timestamp,
    )
    if crud.task_record.get(db, update.task_id) is None:
        crud.task_record.create(db, update.task_id, **fields)
    else:
        crud.task_record.update(db, update.task_id, **fields)


def save_plan_progress(db: Session, robot_id: str, message: PlanProgressMsg) -> None:
    plan_id = f"{message.plan_id.destination_session}-{message.plan_id.plan_version}"
    status = "COMPLETED" if message.reached_waypoint == message.target_waypoint else "IN_PROGRESS"
    fields = dict(
        robot_id=robot_id,
        status=status,
        reached_waypoint=message.reached_waypoint,
        target_waypoint=message.target_waypoint,
        reason=None,
        updated_at=datetime.now(timezone.utc),
    )
    if crud.plan_record.get(db, plan_id) is None:
        crud.plan_record.create(db, plan_id, **fields)
    else:
        crud.plan_record.update(db, plan_id, **fields)


def save_plan_error(db: Session, robot_id: str, message: PlanErrorMsg) -> None:
    plan_id = f"{message.plan_id.destination_session}-{message.plan_id.plan_version}"
    fields = dict(
        robot_id=robot_id,
        status="FAILED",
        reached_waypoint=None,
        target_waypoint=None,
        reason=message.details,
        updated_at=datetime.now(timezone.utc),
    )
    if crud.plan_record.get(db, plan_id) is None:
        crud.plan_record.create(db, plan_id, **fields)
    else:
        crud.plan_record.update(db, plan_id, **fields)


@dataclass
class RESPlanServerContext:
    transport: RESPlanServerTransport
    plan_server: RESPlanServer | None
    agent_context: MultiAgentContext | None
    coordinator: MAPFCoordinator | None
    solver: CBSAdapter | None
    # At most one cached plan: the exact {robot_id: goal} problem it solved, paired
    # with robot_id -> (plan, final_waypoint_index). A "plan" call sets it (always
    # overwriting whatever was cached before), a "submit" for the same problem
    # consumes (clears) it.
    plan_cache: tuple[dict[str, str], dict[str, tuple[Plan, int]]] | None

@contextmanager
def make_plan_server(
    config: Settings,
    transport: ServerTransportBase | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> Generator[RESPlanServerContext, None, None]:
    wrapped_transport = RESPlanServerTransport(
        transport,
        plan_server_topic_prefix="rmf2_plan_server/v1",
        plan_executor_topic_prefix=config.plan_executor_topic_prefix,
        session_factory=session_factory,
    )
    wrapped_transport.start()

    if session_factory is not None:
        with session_factory() as session:
            reset_ids = crud.robot_record.reset_all_onboarded(session)
            for robot_id in reset_ids:
                LOGGER.warning("Reset stale onboarded robot on startup: %s", robot_id)

    if config.map_path is None:
        LOGGER.warning("map_path not configured — plan server will not start")
        try:
            yield RESPlanServerContext(
                transport=wrapped_transport,
                plan_server=None,
                agent_context=None,
                coordinator=None,
                solver=None,
                plan_cache=None,
            )
        finally:
            wrapped_transport.stop()
        return

    LOGGER.info("Loading map from %s", config.map_path)
    if session_factory is not None:
        with session_factory() as session:
            crud.lif_record.set_current(session, config.map_path.read_text(), datetime.now(timezone.utc))
    map_data = lif_parser.load_lif(config.map_path)
    grid_map = snap_to_grid(map_data)
    grid_map.obstacles = infer_obstacles(map_data, grid_map)
    LOGGER.info(
        "Grid map '%s': %dx%d, %d nodes, %d obstacles",
        grid_map.map_name,
        grid_map.dimension[0],
        grid_map.dimension[1],
        len(grid_map.grid_nodes),
        len(grid_map.obstacles),
    )

    agent_context = MultiAgentContext()
    solver = CBSAdapter(grid_map)
    coordinator = MAPFCoordinator(agent_context, solver)
    plan_generator = PlanGenerator()

    plan_server = RESPlanServer(
        transport=wrapped_transport,
        context=agent_context,
        coordinator=coordinator,
        plan_generator=plan_generator,
    )

    LOGGER.info("Starting plan server")
    plan_server.start()

    LOGGER.info("Onboarding %d configured robot(s)", len(config.robots))
    batch_result = wrapped_transport.onboard_robot_batch(config.robots)
    if session_factory is not None:
        with session_factory() as session:
            for robot in batch_result.onboarded:
                save_robot(session, robot.robot_id, robot.start_location)
    for robot in batch_result.onboarded:
        LOGGER.info("Onboarded robot %s at %s", robot.robot_id, robot.start_location)
    for robot in batch_result.failed:
        LOGGER.error("Failed to onboard robot %s at %s", robot.robot_id, robot.start_location)

    try:
        yield RESPlanServerContext(
            transport=wrapped_transport,
            plan_server=plan_server,
            agent_context=agent_context,
            coordinator=coordinator,
            solver=solver,
            plan_cache=None,
        )
    finally:
        LOGGER.info("Stopping plan server")
        plan_server.stop()
        wrapped_transport.stop()
