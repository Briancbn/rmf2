from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from vda5050_core.master import OnboardSpec, VDA5050Master
from vda5050_core.transport import create_default_client_shared as create_mqtt_client
from vda5050_core.types import InstantActions

from .config import Settings
from .db_models import AgvRecord
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


def _upsert_agv(session: Session, manufacturer: str, serial_number: str, **kwargs) -> AgvRecord:
    record = session.get(AgvRecord, (manufacturer, serial_number))
    if record is None:
        record = AgvRecord(manufacturer=manufacturer, serial_number=serial_number)
        session.add(record)
    for key, value in kwargs.items():
        setattr(record, key, value)
    return record


def _seed_agvs(session: Session, agvs: list[AgvConfig]) -> None:
    """Insert DB records for AGVs that don't already exist. Never overwrites existing records."""
    for agv in agvs:
        if session.get(AgvRecord, (agv.manufacturer, agv.serial_number)) is None:
            session.add(AgvRecord(manufacturer=agv.manufacturer, serial_number=agv.serial_number))


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

    def _update_if_registered(self, manufacturer: str, serial_number: str, **kwargs) -> bool:
        with self._session_factory() as session:
            if session.get(AgvRecord, (manufacturer, serial_number)) is None:
                return False
            _upsert_agv(session, manufacturer, serial_number, **kwargs)
            session.commit()
        return True

    @staticmethod
    def _parse_agv_id(agv_id: str) -> tuple[str, str]:
        """Parse agv_id string (format: 'manufacturer/serialNumber') into a tuple."""
        parts = agv_id.split("/", 1)
        return (parts[0], parts[1]) if len(parts) == 2 else (agv_id, "")

    def on_connect(self, agv_id: str) -> None:
        manufacturer, serial_number = self._parse_agv_id(agv_id)
        now = datetime.now(timezone.utc)
        conn_json = json.dumps({
            "headerId": 0,
            "timestamp": now.isoformat(),
            "version": "2.0.0",
            "manufacturer": manufacturer,
            "serialNumber": serial_number,
            "connectionState": "ONLINE",
        })
        updated = self._update_if_registered(
            manufacturer, serial_number,
            is_online=True,
            connection_json=conn_json,
            connection_updated_at=now,
        )
        if updated:
            LOGGER.info("AGV connected: %s — sending stateRequest", agv_id)
            for agv in self._agvs:
                if agv.manufacturer == manufacturer and agv.serial_number == serial_number:
                    self._master.publish_instant_actions(manufacturer, serial_number, _make_state_request(agv))
        else:
            LOGGER.debug("Ignoring connect for unregistered AGV: %s", agv_id)

    def on_offline(self, agv_id: str) -> None:
        manufacturer, serial_number = self._parse_agv_id(agv_id)
        now = datetime.now(timezone.utc)
        conn_json = json.dumps({
            "headerId": 0,
            "timestamp": now.isoformat(),
            "version": "2.0.0",
            "manufacturer": manufacturer,
            "serialNumber": serial_number,
            "connectionState": "OFFLINE",
        })
        self._update_if_registered(
            manufacturer, serial_number,
            is_online=False,
            connection_json=conn_json,
            connection_updated_at=now,
        )
        LOGGER.info("AGV offline: %s", agv_id)

    def on_connection_broken(self, agv_id: str) -> None:
        LOGGER.warning("Master-broker connection broken: %s", agv_id)

    def on_connection(self, agv_id: str, connection) -> None:
        LOGGER.debug("VDA5050 connection message from %s (not used for DB updates)", agv_id)

    def on_state(self, agv_id: str, state) -> None:
        state_dict = state.json()
        manufacturer = state_dict.get("manufacturer", "")
        serial_number = state_dict.get("serialNumber", "")
        updated = self._update_if_registered(
            manufacturer,
            serial_number,
            state_json=json.dumps(state_dict),
            state_updated_at=datetime.now(timezone.utc),
        )
        if not updated:
            LOGGER.debug("Ignoring state for unregistered AGV: %s/%s", manufacturer, serial_number)
            return
        LOGGER.info("State updated: %s/%s", manufacturer, serial_number)


@contextmanager
def make_master(config: Settings, session_factory: sessionmaker[Session]) -> Generator[VDA5050Master, None, None]:
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

    master.connect()

    with session_factory() as session:
        _seed_agvs(session, config.agvs)
        session.commit()

        config_keys = {(agv.manufacturer, agv.serial_number) for agv in config.agvs}
        stale_keys = [
            (r.manufacturer, r.serial_number)
            for r in session.scalars(select(AgvRecord).where(AgvRecord.is_onboarded.is_(True))).all()
            if (r.manufacturer, r.serial_number) not in config_keys
        ]
        for mfr, sn in stale_keys:
            LOGGER.warning("Stale onboarded AGV not in current config, offboarding: %s/%s", mfr, sn)
        if stale_keys:
            master.offboard_agv_batch(stale_keys)
            for mfr, sn in stale_keys:
                _upsert_agv(session, mfr, sn, is_onboarded=False, is_online=False)
            session.commit()

    specs = []
    for agv in config.agvs:
        spec = OnboardSpec()
        spec.manufacturer = agv.manufacturer
        spec.serial_number = agv.serial_number
        specs.append(spec)

    result = master.onboard_agv_batch(specs)
    LOGGER.info("Onboarded %d AGV(s), %d failed via %s", len(result.onboarded), len(result.failed), config.mqtt_broker)
    for failed in result.failed:
        LOGGER.error("Failed to onboard AGV: %s/%s", failed.manufacturer, failed.serial_number)

    onboarded_keys = {(s.manufacturer, s.serial_number) for s in result.onboarded}
    with session_factory() as session:
        for agv in config.agvs:
            if (agv.manufacturer, agv.serial_number) in onboarded_keys:
                default_conn = json.dumps({
                    "headerId": 0,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "version": "2.0.0",
                    "manufacturer": agv.manufacturer,
                    "serialNumber": agv.serial_number,
                    "connectionState": "OFFLINE",
                })
                _upsert_agv(
                    session,
                    agv.manufacturer,
                    agv.serial_number,
                    is_onboarded=True,
                    is_online=False,
                    connection_json=default_conn,
                    connection_updated_at=datetime.now(timezone.utc),
                )
        session.commit()

    try:
        yield master
    finally:
        master.offboard_agv_batch([(agv.manufacturer, agv.serial_number) for agv in config.agvs])
        master.disconnect()
        with session_factory() as session:
            for agv in config.agvs:
                _upsert_agv(
                    session,
                    agv.manufacturer,
                    agv.serial_number,
                    is_onboarded=False,
                    is_online=False,
                )
            session.commit()
