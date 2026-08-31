from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class AgvRecord(Base):
    __tablename__ = "agv_records"

    manufacturer: Mapped[str] = mapped_column(String, primary_key=True)
    serial_number: Mapped[str] = mapped_column(String, primary_key=True)
    is_onboarded: Mapped[bool] = mapped_column(default=False)
    is_online: Mapped[bool] = mapped_column(default=False)
    connection_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    connection_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    state_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    state_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
