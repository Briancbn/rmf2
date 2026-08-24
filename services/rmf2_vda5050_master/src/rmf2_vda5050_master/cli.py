"""VDA5050 master service — FastAPI app with instant action endpoints."""

import logging
import os
from contextlib import asynccontextmanager
from uuid import uuid4
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from vda5050_core.types import InstantActions, OperatingMode, State
from vda5050_core.master import VDA5050Master
from vda5050_core.transport import create_mqtt_client

from .model_utils import PyModel
from .models import InstantActionsResultDict

BROKER_URI = os.environ.get("MQTT_BROKER", "tcp://localhost:1883")
MQTT_CLIENT_ID = os.environ.get("MASTER_MQTT_CLIENT_ID", "example-master")
MANUFACTURER = os.environ.get("VDA5050_MANUFACTURER", "Manufacturer")
SERIAL_NUMBER = os.environ.get("VDA5050_SERIAL_NUMBER", "S001")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8011"))

LOGGER = logging.getLogger(__name__)

_master: VDA5050Master | None = None


def _make_state_request() -> InstantActions:
    return InstantActions.from_json(
        {
            "headerId": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "2.0.0",
            "manufacturer": MANUFACTURER,
            "serialNumber": SERIAL_NUMBER,
            "actions": [
                {
                    "actionType": "stateRequest",
                    "actionId": str(uuid4()),
                    "blockingType": "NONE",
                }
            ],
        }
    )


class MasterObserver:
    def on_connect(self, agv_id) -> None:
        LOGGER.info("AGV connected: %s", agv_id)
        if _master is not None:
            _master.publish_instant_actions(MANUFACTURER, SERIAL_NUMBER, _make_state_request())
            LOGGER.info("Sent stateRequest to %s", agv_id)

    def on_offline(self, agv_id) -> None:
        LOGGER.info("AGV offline: %s", agv_id)

    def on_connection_broken(self, agv_id) -> None:
        LOGGER.warning("AGV connection broken: %s", agv_id)

    def on_state(self, agv_id, state) -> None:
        position = state.agv_position
        pose = None if position is None else (position.x, position.y, position.theta)
        LOGGER.info("State: %s", state.json())


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _master
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    mqtt_client = create_mqtt_client(BROKER_URI, MQTT_CLIENT_ID)
    _master = VDA5050Master.make(mqtt_client)
    observer = MasterObserver()

    _master.on_connect(observer.on_connect)
    _master.on_offline(observer.on_offline)
    _master.on_state(observer.on_state)
    _master.on_connection_broken(observer.on_connection_broken)

    _master.connect()
    _master.onboard_agv(MANUFACTURER, SERIAL_NUMBER)
    LOGGER.info("Master listening for %s/%s via %s", MANUFACTURER, SERIAL_NUMBER, BROKER_URI)

    yield

    _master.offboard_agv(MANUFACTURER, SERIAL_NUMBER)
    _master.disconnect()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/states")
def get_all_states(skip: int = 0, limit: int = 100) -> list[PyModel[State]]:
    if _master is None:
        raise HTTPException(status_code=503, detail="Master not ready")

    agvs = list(_master.get_onboarded_agvs())
    return [
        _master.get_agv(mfr, sn).get_last_state()
        for mfr, sn in agvs[skip : skip + limit]
    ]


@app.get("/states/{manufacturer}/{serial_number}")
def get_state(manufacturer: str, serial_number: str) -> PyModel[State]:
    if _master is None:
        raise HTTPException(status_code=503, detail="Master not ready")

    if not _master.is_agv_onboarded(manufacturer, serial_number):
        raise HTTPException(status_code=404, detail="AGV not onboarded")

    state = _master.get_agv(manufacturer, serial_number).get_last_state()
    if state is None:
        raise HTTPException(status_code=404, detail="No state received yet")
    return state


@app.post("/instant_actions/pick_all")
def trigger_pick_all() -> InstantActionsResultDict:
    if _master is None:
        raise HTTPException(status_code=503, detail="Master not ready")

    actions = InstantActions.from_json(
        {
            "headerId": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "2.0.0",
            "manufacturer": MANUFACTURER,
            "serialNumber": SERIAL_NUMBER,
            "actions": [
                {
                    "actionType": "pickAll",
                    "actionId": str(uuid4()),
                    "blockingType": "SOFT",
                }
            ],
        }
    )

    result = _master.assign_instant_actions(MANUFACTURER, SERIAL_NUMBER, actions)
    return InstantActionsResultDict(
        decision=result.decision.name,
        errors=[error.json() for error in result.errors],
    )


def main() -> None:
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
