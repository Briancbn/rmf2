from __future__ import annotations

from fastapi import APIRouter, HTTPException
from vda5050_core.types import State

from ..deps.master import MasterDeps
from ..deps.logger import LoggerDeps
from rmf2_vda5050_master.model_utils import PyModel

router = APIRouter()


@router.get("")
def get_all_states(master: MasterDeps, logger: LoggerDeps, skip: int = 0, limit: int = 100) -> list[PyModel[State]]:
    agvs = list(master.get_onboarded_agvs())
    return [
        master.get_agv(mfr, sn).get_last_state()
        for mfr, sn in agvs[skip : skip + limit]
    ]


@router.get("/{manufacturer}/{serial_number}")
def get_state(master: MasterDeps, logger: LoggerDeps, manufacturer: str, serial_number: str) -> PyModel[State]:
    if not master.is_agv_onboarded(manufacturer, serial_number):
        raise HTTPException(status_code=404, detail="AGV not onboarded")

    state = master.get_agv(manufacturer, serial_number).get_last_state()
    if state is None:
        raise HTTPException(status_code=404, detail="No state received yet")
    return state
