from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from sqlalchemy import select
from vda5050_core.master import OnboardSpec

from ..deps.db import DbSession
from ..deps.logger import LoggerDeps
from ..deps.master import MasterDeps
from rmf2_vda5050_master.db_models import AgvRecord
from rmf2_vda5050_master.master import _upsert_agv
from rmf2_vda5050_master.models import AgvConfig

router = APIRouter()


@router.get("")
def get_onboarded_agvs(db: DbSession, logger: LoggerDeps, skip: int = 0, limit: int = 100) -> list[AgvConfig]:
    records = db.scalars(
        select(AgvRecord)
        .where(AgvRecord.is_onboarded.is_(True))
        .offset(skip)
        .limit(limit)
    ).all()
    return [AgvConfig(manufacturer=r.manufacturer, serial_number=r.serial_number) for r in records]


@router.post("/{manufacturer}/{serial_number}/onboard")
def onboard_agv(manufacturer: str, serial_number: str, master: MasterDeps, db: DbSession, logger: LoggerDeps) -> dict:
    record = db.get(AgvRecord, (manufacturer, serial_number))
    if record is not None and record.is_onboarded:
        raise HTTPException(status_code=409, detail="AGV already onboarded")

    spec = OnboardSpec()
    spec.manufacturer = manufacturer
    spec.serial_number = serial_number

    result = master.onboard_agv_batch([spec])
    if result.failed:
        logger.error("Failed to onboard AGV: %s/%s", manufacturer, serial_number)
        raise HTTPException(status_code=502, detail=f"Master failed to onboard {manufacturer}/{serial_number}")

    default_conn = json.dumps({
        "headerId": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "2.0.0",
        "manufacturer": manufacturer,
        "serialNumber": serial_number,
        "connectionState": "OFFLINE",
    })
    _upsert_agv(
        db,
        manufacturer,
        serial_number,
        is_onboarded=True,
        is_online=False,
        connection_json=default_conn,
        connection_updated_at=datetime.now(timezone.utc),
    )
    db.commit()
    logger.info("Onboarded AGV: %s/%s", manufacturer, serial_number)
    return {"manufacturer": manufacturer, "serial_number": serial_number, "onboarded": True}


@router.post("/{manufacturer}/{serial_number}/offboard")
def offboard_agv(manufacturer: str, serial_number: str, master: MasterDeps, db: DbSession, logger: LoggerDeps) -> dict:
    record = db.get(AgvRecord, (manufacturer, serial_number))
    if record is None or not record.is_onboarded:
        raise HTTPException(status_code=404, detail="AGV not onboarded")

    master.offboard_agv_batch([(manufacturer, serial_number)])
    _upsert_agv(
        db,
        manufacturer,
        serial_number,
        is_onboarded=False,
        is_online=False,
    )
    db.commit()
    logger.info("Offboarded AGV: %s/%s", manufacturer, serial_number)
    return {"manufacturer": manufacturer, "serial_number": serial_number, "onboarded": False}
