from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..deps.db import DbSession
from ..deps.logger import LoggerDeps
from rmf2_vda5050_master.db_models import AgvRecord

router = APIRouter()


@router.get("")
def get_all_states(db: DbSession, logger: LoggerDeps, skip: int = 0, limit: int = 100) -> list[dict]:
    records = db.scalars(
        select(AgvRecord).where(AgvRecord.is_onboarded.is_(True)).offset(skip).limit(limit)
    ).all()
    return [json.loads(r.state_json) for r in records if r.state_json is not None]


@router.get("/{manufacturer}/{serial_number}")
def get_state(db: DbSession, logger: LoggerDeps, manufacturer: str, serial_number: str) -> dict:
    record = db.get(AgvRecord, (manufacturer, serial_number))
    if record is None or not record.is_onboarded:
        raise HTTPException(status_code=404, detail="AGV not onboarded")
    if record.state_json is None:
        raise HTTPException(status_code=404, detail="No state received yet")
    return json.loads(record.state_json)
