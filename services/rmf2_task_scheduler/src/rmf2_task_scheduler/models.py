"""Pydantic wire schemas for the RMF2 Task Scheduler API.

Ported from the reference FastAPI wrapper in ros-industrial/rmf2_scheduler
(rmf2_scheduler_py/rmf2_scheduler/fastapi/schemas.py), adapted to pydantic v2.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, JsonValue
from rmf2_scheduler.data import Process as NativeProcess
from rmf2_scheduler.data import Series as NativeSeries
from rmf2_scheduler.data import Task as NativeTask

from .model_utils import PyModel

_SCHEMAS = Path(__file__).parent / "schemas"

PyModel.register(NativeTask, _SCHEMAS / "task.schema.json")
PyModel.register(NativeProcess, _SCHEMAS / "process.schema.json")
PyModel.register(NativeSeries, _SCHEMAS / "series.schema.json")


class EventBase(BaseModel):
    type: str
    description: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None


class EventCreate(EventBase):
    model_config = ConfigDict(extra="forbid")


class EventUpdate(EventBase):
    model_config = ConfigDict(extra="forbid")


class Event(EventBase):
    id: str
    series_id: Optional[str] = None
    process_id: Optional[str] = None


class TaskBase(EventBase):
    resource_id: Optional[str] = None
    deadline: Optional[datetime] = None
    task_details: Optional[JsonValue] = None


class TaskCreate(TaskBase):
    model_config = ConfigDict(extra="forbid")


class TaskUpdate(TaskBase):
    model_config = ConfigDict(extra="forbid")


class Edge(BaseModel):
    id: str
    type: str = "hard"


class Dependency(BaseModel):
    id: str
    needs: list[Edge]


class ProcessBase(BaseModel):
    graph: list[Dependency]


class ProcessCreate(ProcessBase):
    model_config = ConfigDict(extra="forbid")


class ProcessUpdate(ProcessBase):
    model_config = ConfigDict(extra="forbid")

    status: Optional[str] = None
    current_events: list[str] = []


class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[PyModel[NativeTask]]
    processes: list[PyModel[NativeProcess]]


class EventPayload(EventBase):
    model_config = ConfigDict(extra="forbid")

    id: str


class TaskPayload(TaskBase):
    model_config = ConfigDict(extra="forbid")

    id: str


class ProcessPayload(ProcessBase):
    model_config = ConfigDict(extra="forbid")

    id: str
    process_details: Optional[JsonValue] = {}


class Occurrence(BaseModel):
    id: str
    time: datetime


class SeriesBase(BaseModel):
    type: str
    cron: str
    timezone: str
    until: Optional[datetime] = None


class SeriesPayload(SeriesBase):
    id: str
    occurrences: list[Occurrence]


class SeriesCreate(SeriesPayload):
    model_config = ConfigDict(extra="forbid")


# Series helper classes
class SeriesExpandUntil(BaseModel):
    series_id: str


class SeriesUpdateCron(BaseModel):
    series_id: str
    cron_string: str


class SeriesUpdateOccurrenceTime(BaseModel):
    series_id: str
    occurrence_id: str
    time: datetime


class SeriesDeleteOccurrence(BaseModel):
    series_id: str
    occurrence_id: str


class ScheduleAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    # Payload
    id: Optional[str] = None
    event: Optional[EventPayload] = None
    task: Optional[TaskPayload] = None
    process: Optional[ProcessPayload] = None
    node_id: Optional[str] = None
    source_id: Optional[str] = None
    destination_id: Optional[str] = None
    edge_type: Optional[str] = None
    series_add: Optional[SeriesPayload] = None
    series_expand_until: Optional[SeriesExpandUntil] = None
    series_update_cron: Optional[SeriesUpdateCron] = None
    series_update_occurrence_time: Optional[SeriesUpdateOccurrenceTime] = None
    series_delete_occurrence: Optional[SeriesDeleteOccurrence] = None
    series_delete: Optional[str] = None


class Message(BaseModel):
    """Schema for Message."""

    message: str


class HealthResponse(BaseModel):
    status: str


class InfoResponse(BaseModel):
    service_version: str
    api_version: str
