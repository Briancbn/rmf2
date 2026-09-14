from __future__ import annotations

import json
import random
import string
import typing
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import UUID, uuid4

import pytest

from res_mapf_planning.traffic_dependencies.models.plan import Plan
from res_mapf_planning.traffic_dependencies.models.plan_id import PlanId
from res_plan_server.task_status import TaskStatusUpdate
from res_plan_server.transport.transport_messages import (
    CommittedLocationMsg,
    CommittedLocationsResponseMsg,
    ParticipantDiscoveryMsg,
    PlanErrorMsg,
    PlanIdMsg,
    PlanProgressMsg,
    RobotOnboardMsg,
    TaskRequestMsg,
)

from rmf2_res.transport.json_serializer import JsonSerializer


@dataclass
class Point:
    x: float
    y: float
    name: str | None


@dataclass
class Line:
    a: Point
    b: Point
    name: str


NUM_RANDOM_TESTS = 10

SERIALIZABLE_TYPES = [
    RobotOnboardMsg,
    ParticipantDiscoveryMsg,
    TaskRequestMsg,
    PlanIdMsg,
    CommittedLocationMsg,
    CommittedLocationsResponseMsg,
    PlanProgressMsg,
    PlanErrorMsg,
    TaskStatusUpdate,
    PlanId,
    Plan,
    Line,
]

_UNION_ORIGINS = {typing.Union, getattr(__import__("types"), "UnionType", None)}


class RandomDataGenerator:
    def _random_string(self, length: int = 8) -> str:
        return "".join(random.choices(string.ascii_letters + string.digits, k=length))

    def _random_float(self) -> float:
        return round(random.uniform(-100.0, 100.0), 3)

    def _random_int(self) -> int:
        return random.randint(0, 1000)

    def _random_bool(self) -> bool:
        return random.choice([True, False])

    def _random_enum(self, enum_type: type[Enum]) -> Enum:
        return random.choice(list(enum_type))

    def _random_datetime(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=self._random_int())

    def _random_uuid(self) -> UUID:
        return uuid4()

    def generate(self, type_: type):
        origin = typing.get_origin(type_)

        if origin in _UNION_ORIGINS:
            all_args = typing.get_args(type_)
            args = [a for a in all_args if a is not type(None)]
            if not args:
                return None
            if type(None) in all_args and random.random() < 0.5:
                return None
            return self.generate(args[0])
        if origin is list:
            (item_type,) = typing.get_args(type_)
            return [self.generate(item_type) for _ in range(2)]
        if origin is tuple:
            item_types = typing.get_args(type_)
            return tuple(self.generate(t) for t in item_types)

        if isinstance(type_, type) and issubclass(type_, Enum):
            return self._random_enum(type_)
        if type_ is bool:
            return self._random_bool()
        if type_ is int:
            return self._random_int()
        if type_ is float:
            return self._random_float()
        if type_ is str:
            return self._random_string()
        if type_ is datetime:
            return self._random_datetime()
        if type_ is UUID:
            return self._random_uuid()
        if is_dataclass(type_):
            hints = typing.get_type_hints(type_)
            kwargs = {f.name: self.generate(hints[f.name]) for f in fields(type_)}
            return type_(**kwargs)

        raise TypeError(f"Don't know how to generate a random value for {type_!r}")


_generator = RandomDataGenerator()


def _remove_nulls(data: dict):
    clean_dict = {}
    for key, value in data.items():
        if isinstance(value, dict):
            # Recursively clean the nested dictionary
            nested = _remove_nulls(value)
            # Only keep the nested dictionary if it isn't empty after cleaning
            if nested:
                clean_dict[key] = nested
        elif value is not None:
            clean_dict[key] = value

    return clean_dict


@pytest.mark.parametrize(
    "type_class",
    SERIALIZABLE_TYPES,
    ids=[c.__name__ for c in SERIALIZABLE_TYPES],
)
def test_json_serializer__roundtrip(type_class):
    serializer = JsonSerializer()
    for _ in range(NUM_RANDOM_TESTS):
        obj = _generator.generate(type_class)
        body = serializer.serialize(obj)
        assert serializer.deserialize(body, type_class) == obj


@pytest.mark.parametrize(
    "type_class",
    SERIALIZABLE_TYPES,
    ids=[c.__name__ for c in SERIALIZABLE_TYPES],
)
def test_json_serializer__remove_nulls(type_class):
    serializer = JsonSerializer()
    for _ in range(NUM_RANDOM_TESTS):
        obj = _generator.generate(type_class)
        body = serializer.serialize(obj)
        nulls_removed = json.dumps(_remove_nulls(json.loads(body)))
        assert serializer.deserialize(nulls_removed, type_class) == obj
