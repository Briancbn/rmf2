from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
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
