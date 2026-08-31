from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator
from uuid import uuid4

from vda5050_core.master import VDA5050Master, OnboardSpec
from vda5050_core.transport import create_default_client_shared as create_mqtt_client
from vda5050_core.types import InstantActions

from .config import Settings
from .logger import get_logger
from .models import AgvConfig

LOGGER = get_logger(__name__)


def _make_state_request(agv: AgvConfig) -> InstantActions:
    return InstantActions.from_json(
        {
            "headerId": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "2.0.0",
            "manufacturer": agv.manufacturer,
            "serialNumber": agv.serial_number,
            "actions": [
                {
                    "actionType": "stateRequest",
                    "actionId": str(uuid4()),
                    "blockingType": "NONE",
                }
            ],
        }
    )


class _MasterObserver:
    def __init__(self, master: VDA5050Master, agvs: list[AgvConfig]) -> None:
        self._master = master
        self._agvs = agvs

    def on_connect(self, agv_id) -> None:
        LOGGER.info("AGV connected: %s", agv_id)
        for agv in self._agvs:
            self._master.publish_instant_actions(agv.manufacturer, agv.serial_number, _make_state_request(agv))
        LOGGER.info("Sent stateRequest to all AGVs")

    def on_offline(self, agv_id) -> None:
        LOGGER.info("AGV offline: %s", agv_id)

    def on_connection_broken(self, agv_id) -> None:
        LOGGER.warning("AGV connection broken: %s", agv_id)

    def on_state(self, agv_id, state) -> None:
        LOGGER.info("State: %s", state.json())


@contextmanager
def make_master(config: Settings) -> Generator[VDA5050Master, None, None]:
    client_id = config.master_mqtt_client_id or str(uuid4())
    mqtt_client = create_mqtt_client(config.mqtt_broker, client_id)
    master = VDA5050Master.make(mqtt_client)
    observer = _MasterObserver(master, config.agvs)

    master.on_connect(observer.on_connect)
    master.on_offline(observer.on_offline)
    master.on_state(observer.on_state)
    master.on_connection_broken(observer.on_connection_broken)

    master.connect()

    specs = []
    for agv in config.agvs:
        spec = OnboardSpec()
        spec.manufacturer = agv.manufacturer
        spec.serial_number = agv.serial_number
        specs.append(spec)

    result = master.onboard_agv_batch(specs)
    LOGGER.info("Onboarded %d AGV(s), %d failed via %s", len(result.onboarded), len(result.failed), config.mqtt_broker)

    try:
        yield master
    finally:
        master.offboard_agv_batch([(agv.manufacturer, agv.serial_number) for agv in config.agvs])
        master.disconnect()
