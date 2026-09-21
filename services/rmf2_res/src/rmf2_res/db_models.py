from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from rmf2_res.database import Base


class RobotRecord(Base):
    __tablename__ = "robot_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    robot_id: Mapped[str] = mapped_column(String, index=True, unique=True)
    start_location: Mapped[str] = mapped_column(String)
    is_onboarded: Mapped[bool] = mapped_column(default=False)
    onboarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class TaskRecord(Base):
    __tablename__ = "task_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[str] = mapped_column(String, index=True, unique=True)
    robot_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    superseded_by: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PlanRecord(Base):
    __tablename__ = "plan_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plan_id: Mapped[str] = mapped_column(String, index=True, unique=True)
    robot_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String)
    reached_waypoint: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    target_waypoint: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    reason: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LifRecord(Base):
    """Stores the currently active LIF layout. At most one row (id=1)."""

    __tablename__ = "lif_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    lif_json: Mapped[str] = mapped_column(Text)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # JSON array of all layoutId strings from lif_json, kept in sync for fast lookup
    layout_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # metaInformation fields stored individually for easy lookup
    project_identification: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    creator: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    export_timestamp: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    lif_version: Mapped[str | None] = mapped_column(String, nullable=True, default=None)


class CommittedLocationsRecord(Base):
    __tablename__ = "committed_locations_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    request_id: Mapped[str] = mapped_column(String, index=True, unique=True)
    committed_locations_json: Mapped[str] = mapped_column(Text)
    stationary_agents_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
