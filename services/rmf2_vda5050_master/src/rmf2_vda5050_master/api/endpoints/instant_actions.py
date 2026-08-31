from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter
from vda5050_core.types import InstantActions

from ..deps.master import MasterDeps
from ..deps.logger import LoggerDeps
from rmf2_vda5050_master.config import settings
from rmf2_vda5050_master.models import InstantActionsResultDict

router = APIRouter()


@router.post("/pick_all")
def trigger_pick_all(master: MasterDeps, logger: LoggerDeps) -> list[InstantActionsResultDict]:
    results = []
    for agv in settings().agvs:
        actions = InstantActions.from_json(
            {
                "headerId": 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": "2.0.0",
                "manufacturer": agv.manufacturer,
                "serialNumber": agv.serial_number,
                "actions": [
                    {
                        "actionType": "pickAll",
                        "actionId": str(uuid4()),
                        "blockingType": "SOFT",
                    }
                ],
            }
        )
        result = master.assign_instant_actions(agv.manufacturer, agv.serial_number, actions)
        results.append(InstantActionsResultDict(
            decision=result.decision.name,
            errors=[error.json() for error in result.errors],
        ))
    return results
