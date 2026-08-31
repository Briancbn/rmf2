"""TypedDict models and PyModel schema registrations for vda5050_core types."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from typing_extensions import TypedDict

from vda5050_core.types import InstantActions, State

from .model_utils import PyModel

_SCHEMAS = Path(__file__).parent / "schemas"

PyModel.register(State, _SCHEMAS / "state.schema.json")
PyModel.register(InstantActions, _SCHEMAS / "instantActions.schema.json")


class AgvConfig(BaseModel):
    manufacturer: str
    serial_number: str


class InstantActionsResultDict(TypedDict):
    decision: str
    errors: list[dict]
