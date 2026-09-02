from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


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
