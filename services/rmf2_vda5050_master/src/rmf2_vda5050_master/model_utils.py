"""PyModel: generic annotated bridge between vda5050_core pybind11 types and FastAPI."""

from __future__ import annotations

from typing import Any, Annotated, Generic, TypeVar

T = TypeVar("T")

import json
import re
from pathlib import Path

from pydantic import GetPydanticSchema
from pydantic_core import core_schema

_JsonSchema = dict[str, Any]


def _make_vda_schema(t: type, json_schema: _JsonSchema | None = None):
    def validate(v: Any) -> Any:
        if isinstance(v, dict):
            return t.from_json(v)
        return v

    def serialize(v: Any) -> dict | None:
        return None if v is None else v.json()

    def get_core_schema(tp, handler):
        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                serialize,
                return_schema=core_schema.nullable_schema(core_schema.dict_schema()),
            ),
        )

    def get_json_schema(cs, handler) -> _JsonSchema:
        return json_schema if json_schema is not None else {"type": "object", "title": t.__name__}

    return get_core_schema, get_json_schema


class PyModel(Generic[T]):
    """Annotated bridge for vda5050_core pybind11 types.

    - Input (request body): accepts a dict and calls T.from_json(data)
    - Output (response): calls .json() on the pybind11 object

    Register a JSON schema file for a type so FastAPI can generate accurate docs::

        PyModel.register(State, "schemas/state.json")

    Usage::

        @app.post("/foo")
        def handler(body: PyModel[InstantActions]) -> PyModel[State]:
            ...
    """

    _registry: dict[type, _JsonSchema] = {}

    @classmethod
    def register(cls, t: type, schema_path: str | Path) -> None:
        text = Path(schema_path).read_text()
        text = re.sub(r",\s*([}\]])", r"\1", text)  # strip trailing commas (JSON5)
        cls._registry[t] = json.loads(text)

    def __class_getitem__(cls, t: type) -> type:
        get_core_schema, get_json_schema = _make_vda_schema(t, cls._registry.get(t))
        return Annotated[t, GetPydanticSchema(get_core_schema, get_json_schema)]
