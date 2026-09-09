from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

import networkx as nx
import pika
from pika.adapters.select_connection import SelectConnection
from res_map.map_data import MapData
from res_plan_execution.robot_controllers.base_robot_controller import (
    BaseRobotController,
    WaypointWithCallback,
)

from rmf2_plan_executor.logger import get_logger

LOGGER = get_logger(__name__)

_TOPIC_PREFIX = "rmf2_vda5050_master/v1"
_ASSIGN_ORDER_ROUTING_KEY = _TOPIC_PREFIX.replace("/", ".") + ".assign_order"


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
        "orderId": str(uuid4()),
        "orderUpdateId": 0,
        "nodes": nodes,
        "edges": edges,
    })


class Vda5050RobotController(BaseRobotController):
    """Robot controller that drives robots through rmf2_vda5050_master.

    Publishes a single VDA5050 Order (all plan waypoints in one message) to
    AMQP ``rmf2_vda5050_master/v1/assign_order`` and subscribes to
    ``rmf2_vda5050_master/v1/{manufacturer}/{serial_number}/state`` to detect
    each waypoint arrival via ``lastNodeId``, then fires ``on_reached()``.
    """

    def __init__(
        self,
        map_data: MapData,
        amqp_url: str,
        amqp_exchange: str,
        agent_map: Dict[str, Dict[str, str]],
        lif_path: Optional[Path] = None,
    ) -> None:
        super().__init__(map_data)
        self._amqp_url = amqp_url
        self._amqp_exchange = amqp_exchange
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

        self._running = False
        self._connection: Optional[SelectConnection] = None
        self._channel = None
        self._ioloop_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._ioloop_thread = threading.Thread(
            target=self._run_amqp, daemon=True, name="vda5050-rc-amqp"
        )
        self._ioloop_thread.start()

    def shutdown(self, interrupted: bool = False) -> None:
        self._running = False
        conn = self._connection
        if conn:
            conn.ioloop.add_callback_threadsafe(conn.close)
        if self._ioloop_thread:
            self._ioloop_thread.join(timeout=5.0)
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

        # Build and publish a single VDA5050 Order with all waypoints
        try:
            order_json = _build_order_json(mfr, sn, node_ids, self._graph, self._node_map, self._map_id)
        except Exception:
            LOGGER.exception("Failed to build VDA5050 order for %s", robot_id)
            with self._events_lock:
                for node_id in node_ids:
                    self._arrival_events.get(robot_id, {}).pop(node_id, None)
            return

        self._publish_threadsafe(_ASSIGN_ORDER_ROUTING_KEY, order_json.encode())
        LOGGER.info("Published VDA5050 order to %s for %s/%s", _ASSIGN_ORDER_ROUTING_KEY, mfr, sn)

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

    def _publish_threadsafe(self, routing_key: str, body: bytes) -> None:
        conn = self._connection
        if conn is None:
            LOGGER.error("Cannot publish: AMQP not connected")
            return

        def _do_publish() -> None:
            ch = self._channel
            if ch is None:
                LOGGER.error("Cannot publish: AMQP channel not open")
                return
            ch.basic_publish(
                exchange=self._amqp_exchange,
                routing_key=routing_key,
                body=body,
                properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
            )

        conn.ioloop.add_callback_threadsafe(_do_publish)

    # ---- AMQP state subscription ----

    def _run_amqp(self) -> None:
        while self._running:
            try:
                self._connection = SelectConnection(
                    pika.URLParameters(self._amqp_url),
                    on_open_callback=self._on_connected,
                    on_open_error_callback=self._on_open_error,
                    on_close_callback=self._on_closed,
                )
                self._connection.ioloop.start()
            except Exception as exc:
                LOGGER.warning("AMQP ioloop error: %s", exc)
                self._connection = None
                self._channel = None
            if self._running:
                threading.Event().wait(timeout=5.0)

    def _on_connected(self, connection) -> None:
        connection.channel(on_open_callback=self._on_channel_open)

    def _on_channel_open(self, channel) -> None:
        self._channel = channel
        channel.exchange_declare(
            exchange=self._amqp_exchange,
            exchange_type="topic",
            durable=True,
            callback=self._on_exchange_declared,
        )

    def _on_exchange_declared(self, _frame) -> None:
        LOGGER.info("Vda5050RobotController AMQP connected — subscribing to state topics")
        for robot_id, info in self._agent_map.items():
            self._bind_state_topic(robot_id, info["manufacturer"], info["serial_number"])

    def _bind_state_topic(self, robot_id: str, manufacturer: str, serial_number: str) -> None:
        routing_key = f"{_TOPIC_PREFIX}/{manufacturer}/{serial_number}/state".replace("/", ".")
        channel = self._channel
        if channel is None:
            return
        channel.queue_declare(
            queue="",
            exclusive=True,
            callback=lambda result, rid=robot_id, rk=routing_key: self._on_queue_declared(result, rid, rk),
        )

    def _on_queue_declared(self, result, robot_id: str, routing_key: str) -> None:
        queue_name = result.method.queue
        channel = self._channel
        if channel is None:
            return
        channel.queue_bind(
            exchange=self._amqp_exchange,
            queue=queue_name,
            routing_key=routing_key,
            callback=lambda _: self._on_queue_bound(queue_name, robot_id),
        )

    def _on_queue_bound(self, queue_name: str, robot_id: str) -> None:
        channel = self._channel
        if channel is None:
            return
        channel.basic_consume(
            queue=queue_name,
            on_message_callback=lambda ch, method, props, body: self._on_state(robot_id, body),
            auto_ack=True,
        )

    def _on_state(self, robot_id: str, body: bytes) -> None:
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

    def _on_open_error(self, connection, error) -> None:
        LOGGER.warning("AMQP open error: %s", error)
        self._connection = None
        connection.ioloop.stop()

    def _on_closed(self, connection, reason) -> None:
        LOGGER.warning("AMQP closed: %s", reason)
        self._channel = None
        self._connection = None
        connection.ioloop.stop()
