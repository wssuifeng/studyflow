from __future__ import annotations
from datetime import date, datetime, time
from typing import Optional
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from studyflow.infrastructure.persistence.base import Base, TimestampMixin


class ReviewFeedback(TimestampMixin, Base):
    __tablename__ = "review_feedback"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    detail_markdown: Mapped[str] = mapped_column(Text, default="")
    issue_count: Mapped[int] = mapped_column(Integer, default=0)
    needs_revision: Mapped[bool] = mapped_column(default=False)
    decision: Mapped[str] = mapped_column(String(32), default="PASSED")
    next_action: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="AGENT_CLI")
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(160), nullable=True, unique=True)
    submission: Mapped[Submission] = relationship(back_populates="reviews")
