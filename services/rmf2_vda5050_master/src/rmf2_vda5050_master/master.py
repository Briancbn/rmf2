from __future__ import annotations

import json
import os
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker
from vda5050_core.master import OnboardSpec, VDA5050Master
from vda5050_core.transport import create_default_client_shared as create_mqtt_client
from vda5050_core.types import ConnectionState, InstantActions

from . import crud
from .config import Settings
from .logger import get_logger
from .models import AgvConfig

LOGGER = get_logger(__name__)


def _parse_agv_id(agv_id: str) -> tuple[str, str]:
    parts = agv_id.split("/", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (agv_id, "")


_FRESH_AGV_STATE = {
    "is_onboarded": True,
    "is_online": False,
    "connection_json": None,
    "connection_updated_at": None,
    "state_json": None,
    "state_updated_at": None,
    "factsheet_json": None,
    "factsheet_updated_at": None,
    "active_order_id": None,
}


def save_agv(db: Session, manufacturer: str, serial_number: str) -> None:
    if crud.agv_record.get(db, manufacturer, serial_number) is None:
        crud.agv_record.create(db, manufacturer, serial_number, **_FRESH_AGV_STATE)
    else:
        crud.agv_record.update(db, manufacturer, serial_number, **_FRESH_AGV_STATE)


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
    def __init__(
        self,
        master: VDA5050Master,
        agvs: list[AgvConfig],
        session_factory: sessionmaker[Session],
    ) -> None:
        self._master = master
        self._agvs = agvs
        self._session_factory = session_factory

    def _update_if_registered(
        self, manufacturer: str, serial_number: str, **kwargs
    ) -> bool:
        with self._session_factory() as session:
            if crud.agv_record.get(session, manufacturer, serial_number) is None:
                return False
            crud.agv_record.update(session, manufacturer, serial_number, **kwargs)
        return True

    def on_connect(self, agv_id: str) -> None:
        LOGGER.debug("MQTT connect: %s", agv_id)

    def on_offline(self, agv_id: str) -> None:
        LOGGER.debug("MQTT offline: %s", agv_id)

    def on_connection_broken(self, agv_id: str) -> None:
        LOGGER.warning("Master-broker connection broken: %s", agv_id)

    def on_connection(self, agv_id: str, connection) -> None:
        is_online = connection.connection_state == ConnectionState.ONLINE
        updated = self._update_if_registered(
            connection.header.manufacturer,
            connection.header.serial_number,
            is_online=is_online,
            connection_json=json.dumps(connection.json()),
            connection_updated_at=datetime.fromtimestamp(
                connection.header.timestamp, tz=timezone.utc
            ),
        )
        if not updated:
            LOGGER.debug("Ignoring connection for unregistered AGV: %s", agv_id)
            return
        LOGGER.info("Connection updated: %s — %s", agv_id, connection.connection_state)
        if is_online:
            for agv in self._agvs:
                if (
                    agv.manufacturer == connection.header.manufacturer
                    and agv.serial_number == connection.header.serial_number
                ):
                    self._master.publish_instant_actions(
                        connection.header.manufacturer,
                        connection.header.serial_number,
                        _make_state_request(agv),
                    )

    def on_state(self, agv_id: str, state) -> None:
        updated = self._update_if_registered(
            state.header.manufacturer,
            state.header.serial_number,
            state_json=json.dumps(state.json()),
            state_updated_at=datetime.fromtimestamp(
                state.header.timestamp, tz=timezone.utc
            ),
            active_order_id=state.order_id or None,
        )
        if not updated:
            LOGGER.debug("Ignoring state for unregistered AGV: %s", agv_id)
            return
        LOGGER.info("State updated: %s", agv_id)

    def on_order_complete(self, agv_id: str, order_id: str) -> None:
        manufacturer, serial_number = agv_id.split("/", 1)
        with self._session_factory() as session:
            r = crud.order_record.get_latest_by_order_id(
                session, manufacturer, serial_number, order_id
            )
            if r is not None:
                crud.order_record.update(
                    session,
                    db_obj=r,
                    obj_in={"completed_at": datetime.now(timezone.utc)},
                )
        LOGGER.info("Order completed: %s — %s", agv_id, order_id)

    def on_order_rejected(self, agv_id: str, order_id: str, errors) -> None:
        manufacturer, serial_number = agv_id.split("/", 1)
        with self._session_factory() as session:
            r = crud.order_record.get_latest_by_order_id(
                session, manufacturer, serial_number, order_id
            )
            if r is not None:
                crud.order_record.update(
                    session,
                    db_obj=r,
                    obj_in={"rejected_at": datetime.now(timezone.utc)},
                )
        LOGGER.warning("Order rejected: %s — %s", agv_id, order_id)

    def on_factsheet(self, agv_id: str, factsheet) -> None:
        updated = self._update_if_registered(
            factsheet.header.manufacturer,
            factsheet.header.serial_number,
            factsheet_json=json.dumps(factsheet.json()),
            factsheet_updated_at=datetime.fromtimestamp(
                factsheet.header.timestamp, tz=timezone.utc
            ),
        )
        if not updated:
            LOGGER.debug("Ignoring factsheet for unregistered AGV: %s", agv_id)
            return
        LOGGER.info("Factsheet updated: %s", agv_id)


@contextmanager
def make_master(
    config: Settings, session_factory: sessionmaker[Session]
) -> Generator[VDA5050Master, None, None]:
    base_id = config.master_mqtt_client_id or "rmf2-vda5050-master"
    master_id = f"{base_id}-{os.getpid()}"
    mqtt_client = create_mqtt_client(config.mqtt_broker, master_id)
    master = VDA5050Master.make(mqtt_client)
    observer = _MasterObserver(master, config.agvs, session_factory)

    master.on_connect(observer.on_connect)
    master.on_offline(observer.on_offline)
    master.on_connection_broken(observer.on_connection_broken)
    master.on_connection(observer.on_connection)
    master.on_state(observer.on_state)
    master.on_factsheet(observer.on_factsheet)
    master.on_order_complete(observer.on_order_complete)
    master.on_order_rejected(observer.on_order_rejected)

    master.connect()

    with session_factory() as session:
        reset_ids = crud.agv_record.reset_all_onboarded(session)
        for agv_id in reset_ids:
            LOGGER.warning("Reset stale onboarded AGV on startup: %s", agv_id)

    with session_factory() as session:
        for agv in config.agvs:
            save_agv(session, agv.manufacturer, agv.serial_number)

    specs = []
    for agv in config.agvs:
        spec = OnboardSpec()
        spec.manufacturer = agv.manufacturer
        spec.serial_number = agv.serial_number
        specs.append(spec)

    result = master.onboard_agv_batch(specs)
    LOGGER.info(
        "Onboarded %d AGV(s), %d failed via %s",
        len(result.onboarded),
        len(result.failed),
        config.mqtt_broker,
    )
    if result.failed:
        with session_factory() as session:
            for failed in result.failed:
                LOGGER.error(
                    "Failed to onboard AGV: %s/%s",
                    failed.manufacturer,
                    failed.serial_number,
                )
                crud.agv_record.update(
                    session,
                    failed.manufacturer,
                    failed.serial_number,
                    is_onboarded=False,
                )

    try:
        yield master
    finally:
        master.offboard_agv_batch(
            [(agv.manufacturer, agv.serial_number) for agv in config.agvs]
        )
        master.disconnect()
        with session_factory() as session:
            for agv in config.agvs:
                crud.agv_record.update(
                    session,
                    agv.manufacturer,
                    agv.serial_number,
                    is_onboarded=False,
                )
