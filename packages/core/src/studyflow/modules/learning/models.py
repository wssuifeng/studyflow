from __future__ import annotations
from datetime import date, datetime, time
from typing import Optional
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from studyflow.infrastructure.persistence.base import Base, TimestampMixin


class Submission(TimestampMixin, Base):
    __tablename__ = "submissions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id"), index=True)
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    parent_submission_id: Mapped[Optional[str]] = mapped_column(ForeignKey("submissions.id"), nullable=True, index=True)
    study_session_id: Mapped[Optional[str]] = mapped_column(ForeignKey("course_study_sessions.id"), nullable=True, index=True)
    retest_task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("retest_tasks.id"), nullable=True, index=True)
    batch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    study_session: Mapped[Optional[CourseStudySession]] = relationship()
    answer_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    attempt_kind: Mapped[str] = mapped_column(String(24), default="FIRST")
    next_action: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="USER_WEB")
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(160), nullable=True, unique=True)
    exercise: Mapped[Exercise] = relationship(back_populates="submissions")
    task: Mapped[Optional[Task]] = relationship(back_populates="submissions")
    parent_submission: Mapped[Optional[Submission]] = relationship(remote_side="Submission.id", back_populates="child_submissions")
    child_submissions: Mapped[list[Submission]] = relationship(back_populates="parent_submission")
    reviews: Mapped[list[ReviewFeedback]] = relationship(back_populates="submission", cascade="all, delete-orphan")


class LearningProgress(TimestampMixin, Base):
    __tablename__ = "learning_progress"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="NOT_STARTED", index=True)
    last_position: Mapped[str] = mapped_column(String(500), default="")
    source: Mapped[str] = mapped_column(String(32), default="USER_ENGINE")
    course: Mapped[Course] = relationship()
    lesson: Mapped[Lesson] = relationship()
    __table_args__ = (UniqueConstraint("course_id", "lesson_id", name="uq_learning_progress_course_lesson"),)


class SubmissionWriteReceipt(TimestampMixin, Base):
    __tablename__ = "submission_write_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    operation: Mapped[str] = mapped_column(String(40))
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), index=True)
    payload_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CourseWriteReceipt(TimestampMixin, Base):
    __tablename__ = "course_write_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    study_session_id: Mapped[Optional[str]] = mapped_column(ForeignKey("course_study_sessions.id"), nullable=True, index=True)
    operation: Mapped[str] = mapped_column(String(40))
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)


class CourseStudySession(TimestampMixin, Base):
    """One local learning round: immutable content plus mutable reading position."""
    __tablename__ = "course_study_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    new_version: Mapped[bool] = mapped_column(default=False)
    snapshot_json: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    progress_json: Mapped[str] = mapped_column(Text, default="{}")
    resume_lesson_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    reading_completed: Mapped[bool] = mapped_column(default=False)
    __table_args__ = (UniqueConstraint("course_id", "revision", name="uq_course_study_revision"),)


class StudyNote(TimestampMixin, Base):
    __tablename__ = "study_notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    study_session_id: Mapped[str] = mapped_column(ForeignKey("course_study_sessions.id"), index=True)
    lesson_id: Mapped[str] = mapped_column(String(36))
    text: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("study_session_id", "lesson_id", name="uq_study_note_lesson"),)


class StudyNoteReceipt(TimestampMixin, Base):
    __tablename__ = "study_note_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    study_session_id: Mapped[str] = mapped_column(ForeignKey("course_study_sessions.id"), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)


class PlanNotebook(TimestampMixin, Base):
    """One continuous personal notebook per plan; no homework or round ownership."""
    __tablename__ = "plan_notebooks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_line_id: Mapped[str] = mapped_column(ForeignKey("plan_lines.id"), unique=True)
    blocks_json: Mapped[str] = mapped_column(Text, default="[]")
    version: Mapped[int] = mapped_column(Integer, default=1)


class PlanNotebookReceipt(TimestampMixin, Base):
    __tablename__ = "plan_notebook_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    plan_line_id: Mapped[str] = mapped_column(ForeignKey("plan_lines.id"), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)


class SubmissionChainLink(TimestampMixin, Base):
    """One chosen child per parent; legacy branches remain immutable and auditable."""
    __tablename__ = "submission_chain_links"
    parent_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), primary_key=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), unique=True)
    source: Mapped[str] = mapped_column(String(32), default="USER_ENGINE")
    reason: Mapped[str] = mapped_column(Text, default="")
