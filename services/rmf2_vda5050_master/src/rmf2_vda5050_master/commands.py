from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

COMMANDS_QUEUE = "rmf2.vda5050.commands"


class CommandType(str, Enum):
    ONBOARD = "onboard"
    OFFBOARD = "offboard"
    INSTANT_ACTION = "instant_action"


class Command(BaseModel):
    id: str
    type: CommandType
    manufacturer: str
    serial_number: str
    payload: dict = {}


class CommandResult(BaseModel):
    id: str
    success: bool
    data: dict = {}
    error: str | None = None
