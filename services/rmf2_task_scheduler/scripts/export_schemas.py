"""Generates JSON schemas for the rmf2_scheduler native types this service wraps.

Unlike vda5050_master's scripts/update_schemas.py (which downloads the
official VDA5050 schemas), there's no external canonical schema for
rmf2_scheduler's Task/Process/Series -- so these are generated from small
pydantic "shape" models defined here, matching the exact wire shape the
native objects' .json()/.from_json() already use (see models.py's now
-removed Task/Process/Series classes, which this replaces).

Usage:
    uv run python scripts/export_schemas.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, JsonValue

SCHEMAS_DIR = Path(__file__).parent.parent / "src" / "rmf2_task_scheduler" / "schemas"


class Edge(BaseModel):
    id: str
    type: str = "hard"


class Dependency(BaseModel):
    id: str
    needs: list[Edge]


class Occurrence(BaseModel):
    id: str
    time: datetime


class TaskShape(BaseModel):
    """Mirrors the full Task wire shape produced by rmf2_scheduler.data.Task.json()."""

    model_config = ConfigDict(title="Task")

    type: str
    description: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    resource_id: Optional[str] = None
    deadline: Optional[datetime] = None
    task_details: Optional[JsonValue] = None
    id: str
    series_id: Optional[str] = None
    process_id: Optional[str] = None
    status: str
    planned_start_time: Optional[datetime] = None
    planned_end_time: Optional[datetime] = None
    estimated_duration: Optional[timedelta] = None
    actual_start_time: Optional[datetime] = None
    actual_end_time: Optional[datetime] = None


class ProcessShape(BaseModel):
    """Mirrors the full Process wire shape produced by rmf2_scheduler.data.Process.json()."""

    model_config = ConfigDict(title="Process")

    graph: list[Dependency]
    id: str
    status: Optional[str] = ""
    series_id: Optional[str] = ""
    process_details: Optional[JsonValue] = None
    current_events: list[str] = []


class SeriesShape(BaseModel):
    """Mirrors the full Series wire shape produced by rmf2_scheduler.data.Series.json()."""

    model_config = ConfigDict(title="Series")

    type: str
    cron: str
    timezone: str
    until: Optional[datetime] = None
    occurrences: list[Occurrence]
    exception_ids: Optional[list[str]] = []
    id: str


SCHEMAS: dict[str, type[BaseModel]] = {
    "task.schema.json": TaskShape,
    "process.schema.json": ProcessShape,
    "series.schema.json": SeriesShape,
}


def main() -> None:
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, model in SCHEMAS.items():
        out = SCHEMAS_DIR / filename
        out.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
        print(f"Wrote {out}")


if __name__ == "__main__":
    main()
