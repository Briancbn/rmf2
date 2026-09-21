from __future__ import annotations

import json
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from dataclasses import is_dataclass, asdict

from .serializer import SerializerBase
from dacite import Config, from_dict as dataclass_from_dict

_DACITE_CONFIG = Config(cast=[Enum, UUID, tuple], type_hooks={datetime: datetime.fromisoformat})


def _json_default(obj: Any) -> Any:
    """Handle dataclass field types ``asdict`` leaves as-is: Enum, datetime/date, UUID, set."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    raise TypeError(f"Object of type {type(obj).__name__!r} is not JSON serializable")


class JsonSerializer(SerializerBase):
    """JSON serializer backed by pydantic ``BaseModel`` or the ``json`` module."""

    def serialize(self, message: Any) -> str:
        if isinstance(message, str):
            return message
        if isinstance(message, dict) or isinstance(message, list):
            return json.dumps(message)
        if isinstance(message, BaseModel):
            return message.model_dump_json()
        if callable(getattr(message, "json", None)):
            return json.dumps(message.json())
        if is_dataclass(message):
            return json.dumps(asdict(message), default=_json_default)
        raise TypeError(
            f"Cannot serialize {type(message).__name__!r} for transport publish"
        )

    def deserialize(self, body: str, message_type: type) -> Any:
        if message_type is str:
            return body
        if issubclass(message_type, BaseModel):
            return message_type.model_validate_json(body)
        if hasattr(message_type, "from_json"):
            return message_type.from_json(json.loads(body))
        if is_dataclass(message_type):
            return dataclass_from_dict(message_type, json.loads(body), config=_DACITE_CONFIG)
        raise TypeError(f"Cannot deserialize into {message_type.__name__!r}")
