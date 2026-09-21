"""PyModel: generic annotated bridge between rmf2_scheduler pybind11 types and FastAPI.

Ported from rmf2_vda5050_master's model_utils.py, trimmed down: every
rmf2_scheduler data type (Task, Process, Series, ...) already implements
.json()/.from_json() uniformly, so the getattr-based FromVda5050 fallback
isn't needed here. The JSON-schema-file registry is kept, since (unlike
vda5050_core, which ships the official VDA5050 JSON schemas) there's no
canonical external schema for these types -- see schemas/*.schema.json,
generated from this package's own pydantic "shape" models.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Any, ClassVar, Generic, TypeVar

from fastapi import Body
from pydantic import GetPydanticSchema
from pydantic_core import core_schema

_LOG = logging.getLogger(__name__)

T = TypeVar("T")

_JsonSchema = dict[str, Any]


def _inline_refs(schema: _JsonSchema) -> _JsonSchema:
    """Inline local ``$ref`` entries so the schema is self-contained.

    Pydantic 2's ``GetPydanticSchema`` does not hoist nested ``$defs`` -- any ``$ref``
    it didn't register itself causes a ``KeyError`` during JSON schema generation.
    """
    defs = {**schema.get("definitions", {}), **schema.get("$defs", {})}
    if not defs or '"$ref"' not in json.dumps(schema):
        return schema

    _LOG.warning(
        "Schema '%s' contains local $ref entries; inlining definitions for OpenAPI compatibility.",
        schema.get("title", "<unknown>"),
    )

    def _resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node and len(node) == 1:
                for prefix in ("#/definitions/", "#/$defs/"):
                    if node["$ref"].startswith(prefix):
                        key = node["$ref"][len(prefix):]
                        if key in defs:
                            return _resolve(defs[key])
            return {k: _resolve(v) for k, v in node.items() if k not in ("definitions", "$defs")}
        if isinstance(node, list):
            return [_resolve(item) for item in node]
        return node

    return _resolve(schema)


def _make_schema(py_type: type, json_schema: _JsonSchema | None = None):
    _schema = json_schema

    def validate(value: Any) -> Any:
        if isinstance(value, dict):
            return py_type.from_json(value)
        return value

    def serialize(value: Any) -> dict | None:
        return None if value is None else value.json()

    def get_core_schema(tp: Any, handler: Any) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                serialize,
                return_schema=core_schema.nullable_schema(core_schema.dict_schema()),
            ),
        )

    def get_json_schema(cs: Any, handler: Any) -> _JsonSchema:
        return _schema if _schema is not None else {"type": "object", "title": py_type.__name__}

    return get_core_schema, get_json_schema


class PyModel(Generic[T]):
    """Annotated bridge for rmf2_scheduler pybind11 types.

    - Input (request body): accepts a dict and calls T.from_json(data)
    - Output (response): calls .json() on the pybind11 object

    Register a JSON schema file for a type so FastAPI can generate accurate docs::

        PyModel.register(Task, "schemas/task.schema.json")

    Usage::

        @app.get("/foo")
        def handler() -> PyModel[Task]:
            ...
    """

    _registry: ClassVar[dict[type, _JsonSchema]] = {}

    @classmethod
    def register(
        cls,
        py_type: type,
        schema_path: str | Path,
        property_path: str | None = None,
    ) -> None:
        schema = json.loads(Path(schema_path).read_text())
        if property_path is not None:
            for key in property_path.split("."):
                schema = schema[key]
        cls._registry[py_type] = _inline_refs(schema)

    def __class_getitem__(cls, py_type: type) -> type:
        get_core_schema, get_json_schema = _make_schema(py_type, cls._registry.get(py_type))
        return Annotated[py_type, GetPydanticSchema(get_core_schema, get_json_schema), Body()]
