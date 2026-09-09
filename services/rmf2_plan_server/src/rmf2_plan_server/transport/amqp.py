from __future__ import annotations

import json
import logging
import threading
from typing import Callable, TypeVar

from pika import BasicProperties, URLParameters
from pika.adapters.select_connection import SelectConnection
from pika.channel import Channel
from pika.exchange_type import ExchangeType

from res_mapf_planning.traffic_dependencies.models.plan import Plan
from res_plan_server.task_status import TaskStatusUpdate
from res_plan_server.transport.server_base_transport import ServerBaseTransport
from res_plan_server.transport.transport_messages import (
    CommittedLocationsResponseMsg,
    ParticipantDiscoveryMsg,
    PlanErrorMsg,
    PlanProgressMsg,
    RobotOnboardMsg,
    TaskRequestMsg,
)

from rmf2_plan_server.transport.serializer import (
    encode_dataclass,
    decode_committed_locations_response,
    decode_plan_error,
    decode_plan_progress,
    decode_participant_discovery,
    decode_robot_onboard,
    decode_task_request,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _routing_key(topic: str) -> str:
    return topic.replace("/", ".")


class AmqpServerTransport(ServerBaseTransport):
    def __init__(self, url: str, exchange: str, *, retry_interval: float = 5.0) -> None:
        self._url = url
        self._exchange = exchange
        self._retry_interval = retry_interval

        self._connection: SelectConnection | None = None
        self._channel: Channel | None = None
        self._running = False
        self._stop_event = threading.Event()
        self._ioloop_thread: threading.Thread | None = None

        # (routing_key, raw_callback) pending until channel is ready
        self._pending: list[tuple[str, Callable[[str], None]]] = []
        self._pending_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # ServerBaseTransport — subscriptions                                  #
    # ------------------------------------------------------------------ #

    def subscribe_robot_onboarding(self, callback: Callable[[RobotOnboardMsg], None]) -> None:
        self._subscribe("res/robot_onboard", lambda body: callback(decode_robot_onboard(body)))

    def subscribe_participant_discovery(self, callback: Callable[[ParticipantDiscoveryMsg], None]) -> None:
        self._subscribe("res/participant_discovery", lambda body: callback(decode_participant_discovery(body)))

    def subscribe_task_request(self, robot_id: str, callback: Callable[[TaskRequestMsg], None]) -> None:
        self._subscribe(f"res/task_request/{robot_id}", lambda body: callback(decode_task_request(body)))

    def subscribe_committed_locations_response(self, callback: Callable[[CommittedLocationsResponseMsg], None]) -> None:
        self._subscribe("res/committed_locations_response", lambda body: callback(decode_committed_locations_response(body)))

    def subscribe_plan_progress(self, robot_id: str, callback: Callable[[PlanProgressMsg], None]) -> None:
        self._subscribe(f"res/plan_progress/{robot_id}", lambda body: callback(decode_plan_progress(body)))

    def subscribe_plan_error(self, robot_id: str, callback: Callable[[PlanErrorMsg], None]) -> None:
        self._subscribe(f"res/plan_error/{robot_id}", lambda body: callback(decode_plan_error(body)))

    # ------------------------------------------------------------------ #
    # ServerBaseTransport — publishes                                      #
    # ------------------------------------------------------------------ #

    def publish_plan(self, robot_id: str, plan: Plan) -> None:
        self._publish(f"res/plan/{robot_id}", encode_dataclass(plan))

    def publish_committed_locations_request(self, request_id: str) -> None:
        self._publish("res/committed_locations_request", json.dumps({"request_id": request_id}))

    def publish_task_status(self, update: TaskStatusUpdate) -> None:
        self._publish("res/task_status", encode_dataclass(update))

    # ------------------------------------------------------------------ #
    # Convenience publishes for REST injection                             #
    # ------------------------------------------------------------------ #

    def publish_robot_onboard(self, msg: RobotOnboardMsg) -> None:
        self._publish("res/robot_onboard", encode_dataclass(msg))

    def publish_task_request(self, robot_id: str, msg: TaskRequestMsg) -> None:
        self._publish(f"res/task_request/{robot_id}", encode_dataclass(msg))

    def publish_participant_discovery(self, msg: ParticipantDiscoveryMsg) -> None:
        self._publish("res/participant_discovery", encode_dataclass(msg))

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._ioloop_thread is not None and self._ioloop_thread.is_alive():
            return
        self._running = True
        self._stop_event.clear()
        self._ioloop_thread = threading.Thread(target=self._run, daemon=True, name="amqp-server-ioloop")
        self._ioloop_thread.start()

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        conn = self._connection
        if conn is not None:
            conn.ioloop.add_callback_threadsafe(conn.close)
        if self._ioloop_thread is not None:
            self._ioloop_thread.join(timeout=10.0)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _subscribe(self, topic: str, raw_callback: Callable[[str], None]) -> None:
        rk = _routing_key(topic)
        with self._pending_lock:
            self._pending.append((rk, raw_callback))
        conn = self._connection
        if conn is not None and self._channel is not None:
            conn.ioloop.add_callback_threadsafe(lambda: self._bind_queue(rk, raw_callback))

    def _publish(self, topic: str, body: str) -> None:
        conn = self._connection
        if conn is None or not conn.is_open:
            logger.warning("AMQP publish dropped (not connected): %s", topic)
            return
        rk = _routing_key(topic)
        encoded = body.encode()
        props = BasicProperties(content_type="application/json", delivery_mode=1)

        def _do() -> None:
            ch = self._channel
            if ch is not None and ch.is_open:
                ch.basic_publish(exchange=self._exchange, routing_key=rk, body=encoded, properties=props)

        conn.ioloop.add_callback_threadsafe(_do)

    def _run(self) -> None:
        while self._running:
            try:
                self._connection = SelectConnection(
                    URLParameters(self._url),
                    on_open_callback=self._on_connected,
                    on_open_error_callback=self._on_open_error,
                    on_close_callback=self._on_closed,
                )
                self._connection.ioloop.start()
            except Exception as exc:
                logger.warning("AMQP ioloop error: %s", exc)
                self._connection = None
                self._channel = None
            if self._running:
                self._stop_event.wait(timeout=self._retry_interval)
                self._stop_event.clear()

    def _on_connected(self, connection: SelectConnection) -> None:
        connection.channel(on_open_callback=self._on_channel_open)

    def _on_channel_open(self, channel: Channel) -> None:
        self._channel = channel
        channel.add_on_close_callback(self._on_channel_closed)
        channel.exchange_declare(
            exchange=self._exchange,
            exchange_type=ExchangeType.topic,
            durable=True,
            callback=self._on_exchange_declared,
        )

    def _on_exchange_declared(self, _frame) -> None:
        logger.info("AMQP server transport connected — exchange '%s'", self._exchange)
        with self._pending_lock:
            pending = list(self._pending)
        for rk, cb in pending:
            self._bind_queue(rk, cb)

    def _on_channel_closed(self, channel: Channel, reason: Exception) -> None:
        logger.warning("AMQP channel closed: %s", reason)
        self._channel = None
        conn = self._connection
        if conn is not None and conn.is_open:
            conn.close()

    def _on_open_error(self, connection: SelectConnection, error: Exception) -> None:
        logger.warning("AMQP connection failed, retrying in %.1fs: %s", self._retry_interval, error)
        self._connection = None
        connection.ioloop.stop()

    def _on_closed(self, connection: SelectConnection, reason: Exception) -> None:
        self._channel = None
        self._connection = None
        logger.warning("AMQP connection closed, retrying in %.1fs: %s", self._retry_interval, reason)
        connection.ioloop.stop()

    def _bind_queue(self, routing_key: str, raw_callback: Callable[[str], None]) -> None:
        channel = self._channel
        if channel is None or not channel.is_open:
            return
        channel.queue_declare(
            queue="",
            exclusive=True,
            callback=lambda result: self._on_queue_declared(result, routing_key, raw_callback),
        )

    def _on_queue_declared(self, result, routing_key: str, raw_callback: Callable[[str], None]) -> None:
        queue_name = result.method.queue
        channel = self._channel
        if channel is None or not channel.is_open:
            return
        channel.queue_bind(
            exchange=self._exchange,
            queue=queue_name,
            routing_key=routing_key,
            callback=lambda _: self._on_queue_bound(queue_name, raw_callback),
        )

    def _on_queue_bound(self, queue_name: str, raw_callback: Callable[[str], None]) -> None:
        channel = self._channel
        if channel is None or not channel.is_open:
            return
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(
            queue=queue_name,
            on_message_callback=_make_handler(raw_callback),
            auto_ack=False,
        )


def _make_handler(callback: Callable[[str], None]) -> Callable:
    def handler(channel: Channel, method, _properties, body: bytes) -> None:
        try:
            callback(body.decode())
        except Exception as exc:
            logger.error("Handler error: %s", exc)
        channel.basic_ack(delivery_tag=method.delivery_tag)
    return handler
