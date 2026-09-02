from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from vda5050_core.types import Order

from rmf2_vda5050_master import crud
from rmf2_vda5050_master.model_utils import PyModel
from rmf2_vda5050_master.models import OrderAssignmentResultModel, OrderStatus

from ..deps.db import DbSession
from ..deps.logger import LoggerDeps
from ..deps.master import MasterDeps

router = APIRouter()


@router.get("")
def get_all_orders(
    db: DbSession,
    logger: LoggerDeps,
    skip: int = 0,
    limit: int = 100,
) -> list[PyModel[Order]]:
    records = crud.order_record.get_multi(db, skip=skip, limit=limit)
    return [json.loads(r.order_json) for r in records]


@router.get("/{manufacturer}/{serial_number}", response_model_exclude_none=True)
def get_agv_orders(
    manufacturer: str,
    serial_number: str,
    db: DbSession,
    logger: LoggerDeps,
    skip: int = 0,
    limit: int = 100,
    show_order: bool = False,
) -> list[OrderStatus]:
    records = crud.order_record.get_by_agv(
        db, manufacturer, serial_number, skip=skip, limit=limit
    )
    ctx = {"show_order": show_order}
    return [OrderStatus.model_validate(r, context=ctx) for r in records]


@router.get("/{manufacturer}/{serial_number}/active")
def get_active_order(
    manufacturer: str,
    serial_number: str,
    db: DbSession,
    logger: LoggerDeps,
) -> PyModel[Order]:
    agv = crud.agv_record.get(db, manufacturer, serial_number)
    if agv is None or not agv.is_onboarded:
        raise HTTPException(status_code=404, detail="AGV not onboarded")
    if agv.active_order_id is None:
        raise HTTPException(status_code=404, detail="No active order")
    record = crud.order_record.get_latest_by_order_id(
        db, manufacturer, serial_number, agv.active_order_id
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Active order record not found")
    return json.loads(record.order_json)


def _do_assign(
    manufacturer: str,
    serial_number: str,
    order: Order,
    master,
    db,
    logger,
) -> OrderAssignmentResultModel:
    if not master.is_agv_onboarded(manufacturer, serial_number):
        raise HTTPException(
            status_code=404,
            detail=f"AGV not onboarded: {manufacturer}/{serial_number}",
        )
    result = master.assign_order(manufacturer, serial_number, order)
    logger.info(
        "Order assigned to %s/%s: %s", manufacturer, serial_number, result.decision
    )
    crud.order_record.create(
        db,
        manufacturer=manufacturer,
        serial_number=serial_number,
        order_id=order.order_id,
        order_update_id=order.order_update_id,
        order_json=json.dumps(order.json()),
        assigned_at=datetime.now(timezone.utc),
    )
    return OrderAssignmentResultModel.from_vda5050(result)


@router.post("/{manufacturer}/{serial_number}/assign")
def assign_order(
    manufacturer: str,
    serial_number: str,
    order: PyModel[Order],
    master: MasterDeps,
    db: DbSession,
    logger: LoggerDeps,
) -> OrderAssignmentResultModel:
    return _do_assign(manufacturer, serial_number, order, master, db, logger)


@router.post("/assign")
def assign_orders(
    orders: list[PyModel[Order]],
    master: MasterDeps,
    db: DbSession,
    logger: LoggerDeps,
) -> list[OrderAssignmentResultModel]:
    return [
        _do_assign(
            order.header.manufacturer,
            order.header.serial_number,
            order,
            master,
            db,
            logger,
        )
        for order in orders
    ]
