from __future__ import annotations

from fastapi import APIRouter, HTTPException
from vda5050_core.types import InstantActions

from rmf2_vda5050_master.model_utils import PyModel
from rmf2_vda5050_master.models import InstantActionAssignmentResult

from ..deps.logger import LoggerDeps
from ..deps.master import MasterDeps

router = APIRouter()


def _do_assign(
    manufacturer: str,
    serial_number: str,
    actions: InstantActions,
    master,
    logger,
) -> InstantActionAssignmentResult:
    if not master.is_agv_onboarded(manufacturer, serial_number):
        raise HTTPException(
            status_code=404,
            detail=f"AGV not onboarded: {manufacturer}/{serial_number}",
        )
    result = master.assign_instant_actions(manufacturer, serial_number, actions)
    logger.info(
        "InstantActions sent to %s/%s — decision: %s",
        manufacturer,
        serial_number,
        result.decision,
    )
    return InstantActionAssignmentResult.from_vda5050(result)


@router.post("/{manufacturer}/{serial_number}/assign")
def assign_instant_actions(
    manufacturer: str,
    serial_number: str,
    actions: PyModel[InstantActions],
    master: MasterDeps,
    logger: LoggerDeps,
) -> InstantActionAssignmentResult:
    return _do_assign(manufacturer, serial_number, actions, master, logger)


@router.post("/assign")
def assign_instant_actions_batch(
    actions_list: list[PyModel[InstantActions]],
    master: MasterDeps,
    logger: LoggerDeps,
) -> list[InstantActionAssignmentResult]:
    return [
        _do_assign(
            a.header.manufacturer,
            a.header.serial_number,
            a,
            master,
            logger,
        )
        for a in actions_list
    ]
