"""RMF2 Plan Executor — context manager for plan executor lifecycle."""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from res_map import lif_parser
from res_map.map_data import MapData
from res_mapf_planning.traffic_dependencies.models.plan import Plan
from res_plan_execution.plan_execution.dependency_manager import DependencyManager
from res_plan_execution.plan_execution.plan_executor import PlanExecutor
from res_plan_execution.plan_execution.transport.executor_base_transport import ExecutorBaseTransport
from res_plan_server.task_status import TaskStatusUpdate
from res_plan_server.transport.transport_messages import (
    CommittedLocationsResponseMsg,
    ParticipantDiscoveryMsg,
    PlanErrorMsg,
    PlanProgressMsg,
    RobotOnboardMsg,
)

from rmf2_res import crud
from rmf2_res.logger import get_logger
from rmf2_res.rmf2_plan_executor.config import Settings
from rmf2_res.rmf2_plan_executor.robot_controller import Vda5050RobotController
from rmf2_res.transport import PublisherBase, ServerTransportAmqp, ServerTransportBase, SubscriberBase, WrappedCallback

LOGGER = get_logger(__name__)


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


def save_committed_locations(db: Session, message: CommittedLocationsResponseMsg) -> None:
    fields = dict(
        committed_locations_json=json.dumps([asdict(location) for location in message.committed_locations]),
        stationary_agents_json=json.dumps(list(message.stationary_agents)),
        updated_at=datetime.now(timezone.utc),
    )
    if crud.committed_locations_record.get(db, message.request_id) is None:
        crud.committed_locations_record.create(db, message.request_id, **fields)
    else:
        crud.committed_locations_record.update(db, message.request_id, **fields)


class RESPlanExecutorTransport(ExecutorBaseTransport):
    """ExecutorBaseTransport implementation that maps the plan executor's typed
    pub/sub onto a generic :class:`ServerTransportBase`, mirroring how
    ``RESPlanServerTransport`` adapts the plan server side.

    Also stores each subscribed callback, keyed the same way as the AMQP topic,
    so it can be invoked directly (bypassing AMQP) — used by the debug injection
    endpoints the same way ``RESPlanServerTransport.onboard_robot``/``submit_task``
    let the plan server's HTTP API drive its callbacks directly.
    """

    def __init__(
        self,
        transport: ServerTransportBase,
        topic_prefix: str | None = None,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._transport = transport
        self._topic_prefix = topic_prefix
        self._session_factory = session_factory
        self._publishers: dict[str, PublisherBase] = {}
        self._subscribers: list[SubscriberBase] = []
        self._callbacks: dict[str, WrappedCallback] = {}

    def _full(self, topic: str) -> str:
        return f"{self._topic_prefix}/{topic}" if self._topic_prefix else topic

    def _subscribe(self, message_type: type, topic: str, callback: Callable) -> None:
        self._subscribers.append(self._transport.create_subscriber(message_type, topic, callback))

    def _publish_message(self, message_type: type, topic: str, message: Any) -> None:
        publisher = self._publishers.get(topic)
        if publisher is None:
            publisher = self._transport.create_publisher(message_type, topic)
            self._publishers[topic] = publisher
        publisher.publish(message)

    # ------------------------------------------------------------------ #
    # Exposed callbacks                                                  #
    # ------------------------------------------------------------------ #

    def onboard_robot(self, robot: RobotOnboardMsg) -> None:
        callback = self._callbacks.get("robot_onboard")
        if callback is None:
            LOGGER.warning("Plan Executor is not initialized!")
            return
        callback(robot)

    def discover_participants(self, message: ParticipantDiscoveryMsg) -> None:
        callback = self._callbacks.get("participant_discovery")
        if callback is None:
            LOGGER.warning("Plan Executor is not initialized!")
            return
        callback(message)

    def submit_plan(self, robot_id: str, plan: Plan) -> None:
        callback = self._callbacks.get(f"plan:{robot_id}")
        if callback is None:
            LOGGER.warning("No plan subscription for robot %s", robot_id)
            return
        callback(plan)

    def request_committed_locations(self, request_id: str) -> None:
        callback = self._callbacks.get("committed_locations_request")
        if callback is None:
            LOGGER.warning("Plan Executor is not initialized!")
            return
        callback(request_id)

    # ------------------------------------------------------------------ #
    # ExecutorBaseTransport — subscriptions                                #
    # ------------------------------------------------------------------ #

    def subscribe_robot_onboarding(self, callback: Callable[[RobotOnboardMsg], None]) -> None:
        def post_save_robot(robot: RobotOnboardMsg) -> None:
            if self._session_factory is not None:
                with self._session_factory() as session:
                    save_robot(session, robot.robot_id, robot.start_location)

        wrapped_callback = WrappedCallback(callback, post=post_save_robot)
        self._callbacks["robot_onboard"] = wrapped_callback
        self._subscribe(RobotOnboardMsg, self._full("robot_onboard"), wrapped_callback)

    def subscribe_participant_discovery(self, callback: Callable[[ParticipantDiscoveryMsg], None]) -> None:
        wrapped_callback = WrappedCallback(callback)
        self._callbacks["participant_discovery"] = wrapped_callback
        self._subscribe(ParticipantDiscoveryMsg, self._full("participant_discovery"), wrapped_callback)

    def subscribe_plan(self, robot_id: str, callback: Callable[[Plan], None]) -> None:
        wrapped_callback = WrappedCallback(callback)
        self._callbacks[f"plan:{robot_id}"] = wrapped_callback
        self._subscribe(Plan, self._full(f"{robot_id}/plan"), wrapped_callback)

    def subscribe_committed_locations_request(self, callback: Callable[[str], None]) -> None:
        wrapped_callback = WrappedCallback(callback)
        self._callbacks["committed_locations_request"] = wrapped_callback

        def _on_request(body: str) -> None:
            wrapped_callback(json.loads(body)["request_id"])

        self._subscribe(str, self._full("committed_locations/request"), _on_request)

    # ------------------------------------------------------------------ #
    # ExecutorBaseTransport — publishes                                    #
    # ------------------------------------------------------------------ #

    def publish_progress(self, robot_id: str, progress_msg: PlanProgressMsg) -> None:
        self._publish_message(PlanProgressMsg, self._full(f"{robot_id}/plan/progress"), progress_msg)
        if self._session_factory is not None:
            with self._session_factory() as session:
                save_plan_progress(session, robot_id, progress_msg)

    def publish_plan_error(self, robot_id: str, error_msg: PlanErrorMsg) -> None:
        self._publish_message(PlanErrorMsg, self._full(f"{robot_id}/plan/error"), error_msg)
        if self._session_factory is not None:
            with self._session_factory() as session:
                save_plan_error(session, robot_id, error_msg)

    def publish_committed_locations_response(self, response_msg: CommittedLocationsResponseMsg) -> None:
        self._publish_message(CommittedLocationsResponseMsg, self._full("committed_locations/response"), response_msg)
        if self._session_factory is not None:
            with self._session_factory() as session:
                save_committed_locations(session, response_msg)

    def publish_task_status(self, update: TaskStatusUpdate) -> None:
        # res_plan_execution's PlanExecutor._handle_plan passes
        # plan.plan_id.destination_session (a UUID) as task_id when publishing
        # SUPERSEDED — always coerce so it can be serialized/persisted.
        update.task_id = str(update.task_id)
        self._publish_message(TaskStatusUpdate, self._full("task_status"), update)
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


@dataclass
class PlanExecutorContext:
    transport: RESPlanExecutorTransport
    robot_controller: Vda5050RobotController
    executor: PlanExecutor


@contextmanager
def make_plan_executor(
    config: Settings, session_factory: sessionmaker[Session] | None = None
) -> Generator[PlanExecutorContext, None, None]:
    map_data = lif_parser.load_lif(config.map_path) if config.map_path else MapData(world_positions={}, world_position_to_name={}, edges=[])

    if config.map_path is not None and session_factory is not None:
        with session_factory() as session:
            crud.lif_record.set_current(session, config.map_path.read_text(), datetime.now(timezone.utc))

    agent_map = {
        a.agent_id: {"manufacturer": a.manufacturer, "serial_number": a.serial_number}
        for a in config.agents
    }

    raw_transport = ServerTransportAmqp.from_url(config.amqp.url, config.amqp.exchange)
    transport = RESPlanExecutorTransport(raw_transport, topic_prefix=config.topic_prefix, session_factory=session_factory)
    transport.start()

    robot_controller = Vda5050RobotController(
        map_data=map_data,
        transport=raw_transport,
        agent_map=agent_map,
        lif_path=config.map_path,
    )
    executor = PlanExecutor(transport=transport, robot_controller=robot_controller, dependency_manager=DependencyManager())

    robot_controller.start()
    executor.start()

    LOGGER.info("Onboarding %d configured robot(s)", len(config.robots))
    for robot in config.robots:
        transport.onboard_robot(robot)
        LOGGER.info("Onboarded robot %s at %s", robot.robot_id, robot.start_location)

    try:
        yield PlanExecutorContext(transport=transport, robot_controller=robot_controller, executor=executor)
    finally:
        executor.stop()
        robot_controller.shutdown()
        transport.stop()
