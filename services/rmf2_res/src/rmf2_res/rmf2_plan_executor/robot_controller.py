from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

import networkx as nx
from res_map.map_data import MapData
from res_plan_execution.robot_controllers.base_robot_controller import (
    BaseRobotController,
    WaypointWithCallback,
)
from res_plan_server.transport.transport_messages import PlanErrorCode

from rmf2_res.logger import get_logger
from rmf2_res.transport import PublisherBase, ServerTransportBase, SubscriberBase

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


def _build_order_json(
    manufacturer: str,
    serial_number: str,
    node_ids: list[str],
    graph: nx.DiGraph,
    node_map: dict,
    map_id: str,
    order_id: str,
) -> str:
    nodes = []
    for seq, node_id in enumerate(node_ids):
        pos = node_map.get(node_id, {}).get("nodePosition", {})
        nodes.append({
            "nodeId": node_id,
            "sequenceId": seq * 2,
            "released": True,
            "nodePosition": {
                "x": pos.get("x", 0.0),
                "y": pos.get("y", 0.0),
                "mapId": map_id,
                "allowedDeviationXY": pos.get("allowedDeviationXY", 0.0),
                "allowedDeviationTheta": pos.get("allowedDeviationTheta", 0.0),
            },
            "actions": [],
        })
    edges = []
    for i in range(len(node_ids) - 1):
        src, dst = node_ids[i], node_ids[i + 1]
        edge_data = graph[src][dst]["edge_data"]
        edges.append({
            "edgeId": edge_data["edgeId"],
            "sequenceId": i * 2 + 1,
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
        "orderUpdateId": 0,
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
        lif_path: Optional[Path] = None,
    ) -> None:
        super().__init__(map_data)
        self._transport = transport
        self._agent_map = agent_map

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
                self._transport.create_subscriber(str, topic, lambda body, rid=robot_id: self._on_state(rid, body))
            )
        LOGGER.info("Vda5050RobotController subscribed to state and order-result topics")

    def shutdown(self, interrupted: bool = False) -> None:
        for subscriber in self._subscribers:
            subscriber.unsubscribe()
        self._subscribers.clear()
        LOGGER.info("Vda5050RobotController shut down (interrupted=%s)", interrupted)

    def enqueue(self, robot_id: str, waypoints_with_callbacks: List[WaypointWithCallback]) -> None:
        threading.Thread(
            target=self._execute_plan,
            args=(robot_id, waypoints_with_callbacks),
            daemon=True,
            name=f"vda5050-rc-{robot_id}",
        ).start()

    def _execute_plan(
        self, robot_id: str, waypoints_with_callbacks: List[WaypointWithCallback]
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

        LOGGER.info("Robot %s: planning order through %s", robot_id, node_ids)

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
        order_id = str(uuid4())
        result_event = threading.Event()
        with self._order_lock:
            self._order_result_events[order_id] = result_event

        # Build and publish a single VDA5050 Order with all waypoints
        try:
            order_json = _build_order_json(mfr, sn, node_ids, self._graph, self._node_map, self._map_id, order_id)
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
