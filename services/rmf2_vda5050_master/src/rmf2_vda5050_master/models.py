"""TypedDict models and PyModel schema registrations for vda5050_core types."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)
from typing_extensions import Self, TypedDict
from vda5050_core.master import (
    OnboardSpec as _VdaOnboardSpec,
)
from vda5050_core.types import Connection, ConnectionState, InstantActions, State

from .model_utils import FromVda5050, PyModel

_SCHEMAS = Path(__file__).parent / "schemas"

PyModel.register(State, _SCHEMAS / "state.schema.json")
PyModel.register(InstantActions, _SCHEMAS / "instantActions.schema.json")
PyModel.register(Connection, _SCHEMAS / "connection.schema.json")

_connection_adapter = TypeAdapter(PyModel[Connection])


class AgvConfig(BaseModel):
    manufacturer: str
    serial_number: str


class AgvStatus(AgvConfig):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    is_online: bool
    state: PyModel[State] | None = Field(None, validation_alias="state_json")
    connection: PyModel[Connection] | None = Field(
        None, validation_alias="connection_json"
    )

    @field_validator("state", "connection", mode="before")
    @classmethod
    def _parse_json(cls, value: str | None, info: ValidationInfo) -> dict | None:
        if not (info.context or {}).get(f"show_{info.field_name}", False):
            return None
        return json.loads(value) if value is not None else None


class OffboardSpec(BaseModel):
    manufacturer: str = Field(description="AGV manufacturer identifier")
    serial_number: str = Field(description="AGV serial number")


class OnboardSpec(FromVda5050):
    manufacturer: str
    serial_number: str
    max_queue_size: int = 10
    drop_oldest: bool = True

    def to_vda5050(self) -> _VdaOnboardSpec:
        return _VdaOnboardSpec(**self.model_dump())


class BatchOnboardResult(FromVda5050):
    onboarded: list[OnboardSpec]
    failed: list[OnboardSpec]
    skipped_already_onboarded: list[OnboardSpec]


class InstantActionsResultDict(TypedDict):
    decision: str
    errors: list[dict]


class DeviceConnection(BaseModel):
    timestamp: str
    deviceId: str
    connectionState: Literal["ONLINE", "OFFLINE"]

    @model_validator(mode="before")
    @classmethod
    def from_vda5050_connection(cls, data) -> Self:
        conn: Connection = _connection_adapter.validate_python(data)
        return cls.model_construct(
            timestamp=datetime.fromtimestamp(
                conn.header.timestamp, tz=timezone.utc
            ).isoformat(),
            deviceId=f"{conn.header.manufacturer}/{conn.header.serial_number}",
            connectionState="ONLINE"
            if conn.connection_state == ConnectionState.ONLINE
            else "OFFLINE",
        )
