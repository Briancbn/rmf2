"""TypedDict models and PyModel schema registrations for vda5050_core types."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, TypeAdapter, model_validator
from typing_extensions import TypedDict
from vda5050_core.types import Connection, InstantActions, State

from .model_utils import PyModel

_SCHEMAS = Path(__file__).parent / "schemas"

PyModel.register(State, _SCHEMAS / "state.schema.json")
PyModel.register(InstantActions, _SCHEMAS / "instantActions.schema.json")
PyModel.register(Connection, _SCHEMAS / "connection.schema.json")

_connection_adapter: TypeAdapter[Connection] = TypeAdapter(PyModel[Connection])


class AgvConfig(BaseModel):
    manufacturer: str
    serial_number: str


class InstantActionsResultDict(TypedDict):
    decision: str
    errors: list[dict]


class DeviceConnection(BaseModel):
    timestamp: str
    deviceId: str
    connectionState: Literal["ONLINE", "OFFLINE"]

    @model_validator(mode="before")
    @classmethod
    def from_connection(cls, data) -> dict:
        conn: Connection = _connection_adapter.validate_python(data)
        d = conn.json()
        vda_state = d.get("connectionState", "OFFLINE")
        return {
            "timestamp": d.get("timestamp", ""),
            "deviceId": f"{d['manufacturer']}/{d['serialNumber']}",
            "connectionState": "ONLINE" if vda_state == "ONLINE" else "OFFLINE",
        }
