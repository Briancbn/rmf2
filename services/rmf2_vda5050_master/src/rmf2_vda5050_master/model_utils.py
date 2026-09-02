"""PyModel: generic annotated bridge between vda5050_core pybind11 types and FastAPI."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, GetPydanticSchema, model_validator
from pydantic_core import core_schema
from typing_extensions import Self

T = TypeVar("T")

_JsonSchema = dict[str, Any]


class FromVda5050(BaseModel):
    """Base class that auto-maps pybind11 vda5050 objects to Pydantic models via model_fields.

    TODO: replace field-by-field getattr mapping with native C++ JSON serialization
    (obj.json()) and validate against the vda5050 JSON schema, consistent with how
    PyModel handles State/Connection/InstantActions.
    """

    @model_validator(mode="before")
    @classmethod
    def _coerce_from_pybind(cls, data: Any) -> Any:
        if not isinstance(data, (dict, BaseModel)):
            return {field: getattr(data, field) for field in cls.model_fields}
        return data

    @classmethod
    def from_vda5050(cls, obj: Any) -> Self:
        return cls.model_validate(obj)


def _make_vda_schema(vda_type: type, json_schema: _JsonSchema | None = None):
    def validate(value: Any) -> Any:
        if isinstance(value, dict):
            return vda_type.from_json(value)
        return value

    def serialize(value: Any) -> dict | None:
        return None if value is None else value.json()

    def get_core_schema(tp, handler):
        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                serialize,
                return_schema=core_schema.nullable_schema(core_schema.dict_schema()),
            ),
        )

    def get_json_schema(cs, handler) -> _JsonSchema:
        return (
            json_schema
            if json_schema is not None
            else {"type": "object", "title": vda_type.__name__}
        )

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

    _registry: ClassVar[dict[type, _JsonSchema]] = {}

    @classmethod
    def register(cls, vda_type: type, schema_path: str | Path) -> None:
        text = Path(schema_path).read_text()
        text = re.sub(r",\s*([}\]])", r"\1", text)  # strip trailing commas (JSON5)
        cls._registry[vda_type] = json.loads(text)

    def __class_getitem__(cls, vda_type: type) -> type:
        get_core_schema, get_json_schema = _make_vda_schema(
            vda_type, cls._registry.get(vda_type)
        )
        return Annotated[vda_type, GetPydanticSchema(get_core_schema, get_json_schema)]
