from __future__ import annotations
from datetime import date, datetime, time
from typing import Optional
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from studyflow.infrastructure.persistence.base import Base, TimestampMixin


class ContextSnapshot(TimestampMixin, Base):
    __tablename__ = "context_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    scope: Mapped[str] = mapped_column(String(32), default="today")
    relative_path: Mapped[str] = mapped_column(String(500))
    current_pointer: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
