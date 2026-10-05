from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

import networkx as nx
from res_map.map_data import MapData
from res_plan_execution.plan_execution.dependency_manager import DependencyManager
from res_plan_execution.robot_controllers.base_robot_controller import (
    BaseRobotController,
    WaypointWithCallback,
)
from res_plan_server.transport.transport_messages import PlanErrorCode

from rmf2_res.logger import get_logger
from rmf2_res.transport import PublisherBase, ServerTransportBase, SubscriberBase, WrappedCallback

LOGGER = get_logger(__name__)

_TOPIC_PREFIX = "rmf2_vda5050_master/v1"
_ASSIGN_ORDER_TOPIC = f"{_TOPIC_PREFIX}/assign_order"
_ASSIGN_ORDER_RESULT_TOPIC = f"{_TOPIC_PREFIX}/assign_order_result"


def _build_lif_graph(lif_json: str) -> tuple[nx.DiGraph, dict, str]:
    """Return (graph, node_map, map_id) from a LIF JSON string."""
    lif = json.loads(lif_json)
    layouts = lif.get("layouts", [])
    layout = layouts[0] if layouts else {}
    map_id = layout.get("layoutId", "")
    node_map = {n["nodeId"]: n for n in layout.get("nodes", [])}
    g = nx.DiGraph()
    for node_id in node_map:
        g.add_node(node_id)
    for edge in layout.get("edges", []):
        g.add_edge(edge["startNodeId"], edge["endNodeId"], edge_data=edge)
    return g, node_map, map_id


@dataclass
class _ActiveOrder:
    """The VDA5050 order currently (believed to be) active on an AGV for one task.

    ``last_node``/``next_seq`` are enough to extend it: a later update must not
    resend (let alone change) any already-released base node — vda5050_core rejects
    that ("Update attempts to alter a released base node") — so it should contain
    only genuinely new nodes, with sequenceIds continuing from ``next_seq`` and a
    single bridging edge from ``last_node`` (already released, not re-sent as a node)
    to the first new one.
    """

    order_id: str
    task_id: str
    update_id: int
    last_node: str
    next_seq: int


#: vda5050_core's reachability check only skips comparing positions when the AGV's
#: own last-reported node already equals the order's first node; otherwise it
#: requires the AGV to be within allowedDeviationXY of it. Our nodes are LIF grid
#: coordinates, not the AGV's live (possibly mid-edge, or off-grid) pose, so a 0.0
#: default makes that check fail on any real-world/sim positioning noise.
_ALLOWED_DEVIATION_XY = 1000.0


def _node_entry(node_id: str, seq: int, node_map: dict, map_id: str) -> dict:
    pos = node_map.get(node_id, {}).get("nodePosition", {})
    return {
        "nodeId": node_id,
        "sequenceId": seq,
        "released": True,
        "nodePosition": {
            "x": pos.get("x", 0.0),
            "y": pos.get("y", 0.0),
            "mapId": map_id,
            "allowedDeviationXY": pos.get("allowedDeviationXY", _ALLOWED_DEVIATION_XY),
            "allowedDeviationTheta": pos.get("allowedDeviationTheta", 0.0),
        },
        "actions": [],
    }


def _build_order_json(
    manufacturer: str,
    serial_number: str,
    new_node_ids: list[str],
    graph: nx.DiGraph,
    node_map: dict,
    map_id: str,
    order_id: str,
    order_update_id: int,
    start_seq: int,
    prev_node: str | None,
) -> str:
    """Builds an Order containing ``new_node_ids`` (sequenceIds starting at
    ``start_seq``) plus, if ``prev_node`` is given, the already-released last node
    of the active order re-sent unchanged (at its original ``start_seq - 2``) as
    the splice point, with a bridging edge from it to the first new node.
    """
    nodes = []
    if prev_node is not None:
        nodes.append(_node_entry(prev_node, start_seq - 2, node_map, map_id))
    for i, node_id in enumerate(new_node_ids):
        nodes.append(_node_entry(node_id, start_seq + i * 2, node_map, map_id))
    edges = []
    if prev_node is not None and new_node_ids:
        edge_data = graph[prev_node][new_node_ids[0]]["edge_data"]
        edges.append({
            "edgeId": edge_data["edgeId"],
            "sequenceId": start_seq - 1,
            "startNodeId": prev_node,
            "endNodeId": new_node_ids[0],
            "released": True,
            "actions": [],
        })
    for i in range(len(new_node_ids) - 1):
        src, dst = new_node_ids[i], new_node_ids[i + 1]
        edge_data = graph[src][dst]["edge_data"]
        edges.append({
            "edgeId": edge_data["edgeId"],
            "sequenceId": start_seq + i * 2 + 1,
            "startNodeId": src,
            "endNodeId": dst,
            "released": True,
            "actions": [],
        })
    return json.dumps({
        "headerId": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "2.0.0",
        "manufacturer": manufacturer,
        "serialNumber": serial_number,
        "orderId": order_id,
        "orderUpdateId": order_update_id,
        "nodes": nodes,
        "edges": edges,
    })


class Vda5050RobotController(BaseRobotController):
    """Robot controller that drives robots through rmf2_vda5050_master.

    Publishes a single VDA5050 Order (all plan waypoints in one message) to
    ``rmf2_vda5050_master/v1/assign_order`` and subscribes to
    ``rmf2_vda5050_master/v1/{manufacturer}/{serial_number}/state`` to detect
    each waypoint arrival via ``lastNodeId``, then fires ``on_reached()``.

    Also subscribes to ``rmf2_vda5050_master/v1/assign_order_result`` to detect
    order rejections and report them via ``self._on_robot_failed`` (set by
    ``PlanExecutor.set_failure_callback``).

    Uses the shared :class:`ServerTransportBase` (the same one plan_executor's
    own transport is built on) rather than managing its own AMQP connection.
    """

    def __init__(
        self,
        map_data: MapData,
        transport: ServerTransportBase,
        agent_map: Dict[str, Dict[str, str]],
        dependency_manager: DependencyManager,
        lif_path: Optional[Path] = None,
    ) -> None:
        super().__init__(map_data)
        self._transport = transport
        self._agent_map = agent_map
        self._dm = dependency_manager

        self._graph: Optional[nx.DiGraph] = None
        self._node_map: dict = {}
        self._map_id: str = ""
        if lif_path is not None:
            try:
                self._graph, self._node_map, self._map_id = _build_lif_graph(lif_path.read_text())
                LOGGER.info("LIF graph loaded from %s (%d nodes)", lif_path, len(self._node_map))
            except Exception:
                LOGGER.exception("Failed to load LIF graph from %s", lif_path)

        # Per-robot current node, populated from AMQP state
        self._current_node: Dict[str, Optional[str]] = {}
        self._node_lock = threading.Lock()

        # Per-robot pending arrival events: {robot_id: {node_name: Event}}
        self._arrival_events: Dict[str, Dict[str, threading.Event]] = {}
        self._events_lock = threading.Lock()

        # Per-order assign_order_result correlation: {order_id: Event / result}
        self._order_result_events: Dict[str, threading.Event] = {}
        self._order_results: Dict[str, dict] = {}
        self._order_lock = threading.Lock()

        # Per-robot VDA5050 order believed active on the AGV, so later batches for the
        # same task are sent as order *updates* (same order_id, incremented update_id)
        # instead of a competing order_id the AGV would STITCH_REJECT.
        self._active_orders: Dict[str, _ActiveOrder] = {}
        self._active_orders_lock = threading.Lock()

        # Per-robot lock serializing the resolve→publish→commit critical section in
        # _execute_plan. enqueue() runs each batch in its own thread, and a robot can
        # have more than one batch in flight at once (DependencyManager keeps up to
        # max_enqueued waypoints released ahead of progress) — without this, two
        # batches could both resolve against the same stale active order and publish
        # conflicting/out-of-order updates.
        self._dispatch_locks: Dict[str, threading.Lock] = {}
        self._dispatch_locks_lock = threading.Lock()

        self._order_publisher: Optional[PublisherBase] = None
        self._subscribers: List[SubscriberBase] = []

    def start(self) -> None:
        self._order_publisher = self._transport.create_publisher(str, _ASSIGN_ORDER_TOPIC)
        self._subscribers.append(
            self._transport.create_subscriber(str, _ASSIGN_ORDER_RESULT_TOPIC, self._on_order_result)
        )
        for robot_id, info in self._agent_map.items():
            topic = f"{_TOPIC_PREFIX}/{info['manufacturer']}/{info['serial_number']}/state"
            self._subscribers.append(
                self._transport.create_subscriber(
                    str, topic, WrappedCallback(lambda body, rid=robot_id: self._on_state(rid, body))
                )
            )
        LOGGER.info("Vda5050RobotController subscribed to state and order-result topics")

    def shutdown(self, interrupted: bool = False) -> None:
        for subscriber in self._subscribers:
            subscriber.unsubscribe()
        self._subscribers.clear()
        LOGGER.info("Vda5050RobotController shut down (interrupted=%s)", interrupted)

    def _resolve_start_node(
        self, robot_id: str, waypoints_with_callbacks: List[WaypointWithCallback]
    ) -> Optional[str]:
        """The node the robot is departing from for this batch — the DM's plan waypoint
        immediately preceding the first one in ``waypoints_with_callbacks`` (waypoint 0 is
        the plan's start waypoint, per ``DependencyManager.set_plan``). Computed synchronously
        here (before the batch is handed off to a worker thread) since ``latest_enqueued`` has
        already been advanced past this batch by ``get_valid_waypoints_and_advance`` and would
        race with any later dispatch if read later.
        """
        plan_state = self._dm.get_plan_state(robot_id)
        if plan_state is None:
            return None
        start_idx = plan_state.latest_enqueued - len(waypoints_with_callbacks)
        if start_idx < 0:
            return None
        return plan_state.plan.waypoints[start_idx].name

    def _resolve_order(
        self, robot_id: str, task_id: str, node_ids: list[str]
    ) -> tuple[str, int, str | None, list[str], int]:
        """Returns ``(order_id, order_update_id, prev_node, new_node_ids, start_seq)``.

        If a VDA5050 order for the same ``task_id`` is already active on this robot,
        extends it (same order_id, incremented update_id) instead of minting a
        competing order_id — the AGV rejects a fresh order_id while one is active
        (STITCH_REJECTED). The extension carries only the genuinely new nodes
        (``node_ids`` minus the already-released bridge node at its front, if
        present) with sequenceIds continuing from ``next_seq`` — re-sending an
        already-released node as if new is rejected too ("...alter a released
        base node"). Otherwise starts a new order at update_id 0, sequence 0.
        """
        with self._active_orders_lock:
            active = self._active_orders.get(robot_id)
        if active is not None and active.task_id == task_id:
            new_node_ids = node_ids[1:] if node_ids and node_ids[0] == active.last_node else node_ids
            return active.order_id, active.update_id + 1, active.last_node, new_node_ids, active.next_seq
        return str(uuid4()), 0, None, node_ids, 0

    def _get_dispatch_lock(self, robot_id: str) -> threading.Lock:
        with self._dispatch_locks_lock:
            lock = self._dispatch_locks.get(robot_id)
            if lock is None:
                lock = threading.Lock()
                self._dispatch_locks[robot_id] = lock
            return lock

    def enqueue(self, robot_id: str, waypoints_with_callbacks: List[WaypointWithCallback]) -> None:
        # Resolved unconditionally and synchronously here (racing DM state otherwise,
        # per _resolve_start_node) — whether it's actually needed is decided fresh
        # inside _execute_plan's dispatch-lock critical section, not here, since
        # another batch for this robot may still be in flight (see _get_dispatch_lock).
        start_node = self._resolve_start_node(robot_id, waypoints_with_callbacks)
        threading.Thread(
            target=self._execute_plan,
            args=(robot_id, waypoints_with_callbacks, start_node),
            daemon=True,
            name=f"vda5050-rc-{robot_id}",
        ).start()

    def _execute_plan(
        self,
        robot_id: str,
        waypoints_with_callbacks: List[WaypointWithCallback],
        start_node: Optional[str],
    ) -> None:
        info = self._agent_map.get(robot_id)
        if info is None:
            LOGGER.error("No VDA5050 mapping for robot %s", robot_id)
            return
        if self._graph is None:
            LOGGER.error("No LIF graph loaded — cannot build VDA5050 order for %s", robot_id)
            return

        mfr = info["manufacturer"]
        sn = info["serial_number"]
        node_ids = [wpc.location.name for wpc in waypoints_with_callbacks]
        task_id = waypoints_with_callbacks[0].task_id

        # Serializes resolve→publish→ack→commit per robot: enqueue() can fire another
        # batch for this same robot while this one is still in flight (DM keeps up to
        # max_enqueued waypoints released ahead of progress), and both would otherwise
        # resolve against the same stale active order, publishing conflicting updates.
        with self._get_dispatch_lock(robot_id):
            with self._active_orders_lock:
                active = self._active_orders.get(robot_id)
            # Only a new task needs a resolved start node to bridge from — a continuing
            # task's bridge is the active order's last_node (see _resolve_order).
            is_new_task = active is None or active.task_id != task_id
            if not is_new_task:
                pass  # bridged from the active order's last_node in _resolve_order
            elif start_node is None:
                LOGGER.warning(
                    "Robot %s: could not resolve the DM's start waypoint — VDA5050 order will omit the starting edge",
                    robot_id,
                )
            elif start_node != node_ids[0]:
                node_ids = [start_node, *node_ids]

            LOGGER.info("Robot %s: planning order through %s", robot_id, node_ids)

            order_id, order_update_id, prev_node, new_node_ids, start_seq = self._resolve_order(
                robot_id, task_id, node_ids
            )

            # Register arrival events for all waypoints BEFORE publishing
            events: Dict[str, threading.Event] = {}
            with self._events_lock:
                robot_events = self._arrival_events.setdefault(robot_id, {})
                for node_id in node_ids:
                    ev = threading.Event()
                    robot_events[node_id] = ev
                    events[node_id] = ev

            def _clear_arrival_events() -> None:
                with self._events_lock:
                    for node_id in node_ids:
                        self._arrival_events.get(robot_id, {}).pop(node_id, None)

            # Register order-result correlation BEFORE publishing
            result_event = threading.Event()
            with self._order_lock:
                self._order_result_events[order_id] = result_event

            # Build and publish a single VDA5050 Order — an update of the active order
            # for this task if one exists, else a new one (see _resolve_order)
            try:
                order_json = _build_order_json(
                    mfr,
                    sn,
                    new_node_ids,
                    self._graph,
                    self._node_map,
                    self._map_id,
                    order_id,
                    order_update_id,
                    start_seq,
                    prev_node,
                )
            except Exception:
                LOGGER.exception("Failed to build VDA5050 order for %s", robot_id)
                _clear_arrival_events()
                with self._order_lock:
                    self._order_result_events.pop(order_id, None)
                return

            self._order_publisher.publish(order_json)
            LOGGER.info("Published VDA5050 order %s to %s for %s/%s", order_id, _ASSIGN_ORDER_TOPIC, mfr, sn)

            # Wait briefly for rmf2_vda5050_master's assign_order_result acknowledgement.
            # It publishes this synchronously right after validating the order, so a
            # rejection (e.g. unknown AGV, invalid route) should arrive well within this.
            acknowledged = result_event.wait(timeout=10.0)
            with self._order_lock:
                result = self._order_results.pop(order_id, None)
                self._order_result_events.pop(order_id, None)

            if not acknowledged:
                LOGGER.warning(
                    "No assign_order_result for order %s (robot %s) within timeout — proceeding optimistically",
                    order_id,
                    robot_id,
                )
            elif result is not None and result.get("decision") != "ASSIGNED":
                # rmf2_vda5050_master's OrderAssignmentDecision has exactly one success
                # value ("ASSIGNED") — everything else (AGV_OFFLINE, AGV_NOT_ONBOARDED,
                # AGV_NOT_READY, AGV_MODE_NOT_AUTO, AGV_POSITION_NOT_INITIALIZED,
                # AGV_NO_STATE_YET, AGV_QUEUE_FULL, STITCH_REJECTED, etc.) means the
                # order was not accepted for execution.
                details = (
                    f"VDA5050 order {order_id} not assigned for {robot_id}: "
                    f"{result.get('decision')} {result.get('errors')}"
                )
                LOGGER.error(details)
                _clear_arrival_events()
                self._on_robot_failed(robot_id, PlanErrorCode.INCOMPATIBLE_ACTION, details)
                return

            # Order accepted (or assumed so after an ack timeout) — this is now the
            # active order for the task, so the next batch stitches onto it instead of
            # competing.
            with self._active_orders_lock:
                self._active_orders[robot_id] = _ActiveOrder(
                    order_id=order_id,
                    task_id=task_id,
                    update_id=order_update_id,
                    last_node=new_node_ids[-1] if new_node_ids else prev_node,
                    next_seq=start_seq + len(new_node_ids) * 2,
                )

        # Wait for each waypoint in sequence
        for wpc in waypoints_with_callbacks:
            target = wpc.location.name
            ev = events[target]
            arrived = ev.wait(timeout=120.0)
            with self._events_lock:
                self._arrival_events.get(robot_id, {}).pop(target, None)

            if arrived:
                LOGGER.info("Robot %s reached %s", robot_id, target)
                with self._node_lock:
                    self._current_node[robot_id] = target
                wpc.on_reached()
            else:
                LOGGER.warning("Timeout waiting for robot %s to reach %s", robot_id, target)
                break

    def _on_order_result(self, body: str) -> None:
        try:
            result = json.loads(body)
            order = result.get("order") or {}
            order_id = order.get("orderId")
            if order_id is None:
                return
            with self._order_lock:
                event = self._order_result_events.get(order_id)
                if event is None:
                    return
                self._order_results[order_id] = result
            event.set()
        except Exception:
            LOGGER.exception("Error processing assign_order_result")

    def _on_state(self, robot_id: str, body: str) -> None:
        try:
            state = json.loads(body)
            last_node = state.get("lastNodeId")
            if last_node:
                with self._node_lock:
                    self._current_node[robot_id] = last_node
                with self._events_lock:
                    event = self._arrival_events.get(robot_id, {}).get(last_node)
                if event:
                    event.set()
        except Exception:
            LOGGER.exception("Error processing state for %s", robot_id)
