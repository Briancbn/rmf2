from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class OrderRecord(Base):
    __tablename__ = "order_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    internal_order_id: Mapped[str] = mapped_column(String, index=True)
    manufacturer: Mapped[str] = mapped_column(String, index=True)
    serial_number: Mapped[str] = mapped_column(String, index=True)
    order_id: Mapped[str] = mapped_column(String, index=True)
    order_update_id: Mapped[int] = mapped_column(Integer)
    order_json: Mapped[str] = mapped_column(Text)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class AgvRecord(Base):
    __tablename__ = "agv_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    agv_id: Mapped[str] = mapped_column(String, index=True, unique=True)
    manufacturer: Mapped[str] = mapped_column(String)
    serial_number: Mapped[str] = mapped_column(String)
    is_onboarded: Mapped[bool] = mapped_column(default=False)
    is_online: Mapped[bool] = mapped_column(default=False)
    connection_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    connection_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    state_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    state_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    factsheet_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    factsheet_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    active_order_id: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )
