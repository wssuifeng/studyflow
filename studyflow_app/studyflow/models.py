from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PlanLine(TimestampMixin, Base):
    __tablename__ = "plan_lines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE")
    stages: Mapped[list[Stage]] = relationship(back_populates="plan_line", cascade="all, delete-orphan")
    courses: Mapped[list[Course]] = relationship(back_populates="plan_line", cascade="all, delete-orphan")
    plan_course_items: Mapped[list[PlanCourseItem]] = relationship(back_populates="plan_line", cascade="all, delete-orphan", order_by="PlanCourseItem.sequence_number")
    tasks: Mapped[list[Task]] = relationship(back_populates="plan_line")


class Stage(TimestampMixin, Base):
    __tablename__ = "stages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_line_id: Mapped[str] = mapped_column(ForeignKey("plan_lines.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE")
    plan_line: Mapped[PlanLine] = relationship(back_populates="stages")
    tasks: Mapped[list[Task]] = relationship(back_populates="stage", cascade="all, delete-orphan")


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_line_id: Mapped[Optional[str]] = mapped_column(ForeignKey("plan_lines.id"), nullable=True, index=True)
    stage_id: Mapped[Optional[str]] = mapped_column(ForeignKey("stages.id"), nullable=True, index=True)
    course_schedule_item_id: Mapped[Optional[str]] = mapped_column(ForeignKey("course_schedule_items.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    scheduled_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(24), default="TODO", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    next_action: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=1)
    task_kind: Mapped[str] = mapped_column(String(40), default="OTHER", index=True)
    plan_line: Mapped[Optional[PlanLine]] = relationship(back_populates="tasks")
    stage: Mapped[Optional[Stage]] = relationship(back_populates="tasks")
    course_schedule_item: Mapped[Optional[CourseScheduleItem]] = relationship(back_populates="tasks")
    time_blocks: Mapped[list[TimeBlock]] = relationship(back_populates="task", cascade="all, delete-orphan")
    submissions: Mapped[list[Submission]] = relationship(back_populates="task")


class TimeBlock(TimestampMixin, Base):
    __tablename__ = "time_blocks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    block_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    actual_minutes: Mapped[int] = mapped_column(Integer, default=0)
    task: Mapped[Task] = relationship(back_populates="time_blocks")


class Course(TimestampMixin, Base):
    __tablename__ = "courses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_line_id: Mapped[Optional[str]] = mapped_column(ForeignKey("plan_lines.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(String(120), default="")
    content_type: Mapped[str] = mapped_column(String(40), default="LESSON")
    difficulty: Mapped[str] = mapped_column(String(32), default="")
    source_type: Mapped[str] = mapped_column(String(32), default="AGENT_CLI")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE")
    plan_line: Mapped[Optional[PlanLine]] = relationship(back_populates="courses")
    plan_course_items: Mapped[list[PlanCourseItem]] = relationship(back_populates="course")
    lessons: Mapped[list[Lesson]] = relationship(back_populates="course", cascade="all, delete-orphan", order_by="Lesson.position")


class PlanCourseItem(TimestampMixin, Base):
    __tablename__ = "plan_course_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_line_id: Mapped[str] = mapped_column(ForeignKey("plan_lines.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="PLANNED", index=True)
    planned_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    planned_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    plan_line: Mapped[PlanLine] = relationship(back_populates="plan_course_items")
    course: Mapped[Course] = relationship(back_populates="plan_course_items")
    schedule_items: Mapped[list[CourseScheduleItem]] = relationship(back_populates="plan_course_item", cascade="all, delete-orphan", order_by="CourseScheduleItem.position")
    __table_args__ = (UniqueConstraint("plan_line_id", "course_id", name="uq_plan_course_item_course"),)


class CourseScheduleItem(TimestampMixin, Base):
    __tablename__ = "course_schedule_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_course_item_id: Mapped[str] = mapped_column(ForeignKey("plan_course_items.id"), index=True)
    scheduled_date: Mapped[date] = mapped_column(Date, index=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="PLANNED", index=True)
    plan_course_item: Mapped[PlanCourseItem] = relationship(back_populates="schedule_items")
    tasks: Mapped[list[Task]] = relationship(back_populates="course_schedule_item")
    __table_args__ = (UniqueConstraint("plan_course_item_id", "scheduled_date", name="uq_course_schedule_day"),)


class Lesson(TimestampMixin, Base):
    __tablename__ = "lessons"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=1)
    markdown_path: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text, default="")
    course: Mapped[Course] = relationship(back_populates="lessons")
    exercises: Mapped[list[Exercise]] = relationship(back_populates="lesson", cascade="all, delete-orphan", order_by="Exercise.position")


class Exercise(TimestampMixin, Base):
    __tablename__ = "exercises"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    requirements: Mapped[str] = mapped_column(Text, default="")
    exercise_type: Mapped[str] = mapped_column(String(40), default="SHORT_ANSWER", index=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    lesson: Mapped[Lesson] = relationship(back_populates="exercises")
    submissions: Mapped[list[Submission]] = relationship(back_populates="exercise", cascade="all, delete-orphan")


class Submission(TimestampMixin, Base):
    __tablename__ = "submissions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id"), index=True)
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    parent_submission_id: Mapped[Optional[str]] = mapped_column(ForeignKey("submissions.id"), nullable=True, index=True)
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


class CourseWriteReceipt(TimestampMixin, Base):
    __tablename__ = "course_write_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    operation: Mapped[str] = mapped_column(String(40))
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    relative_path: Mapped[str] = mapped_column(String(500), unique=True)
    document_type: Mapped[str] = mapped_column(String(40), default="MARKDOWN")
    status: Mapped[str] = mapped_column(String(24), default="PRESENT", index=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    modified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    summary: Mapped[str] = mapped_column(Text, default="")


class ContextSnapshot(TimestampMixin, Base):
    __tablename__ = "context_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    scope: Mapped[str] = mapped_column(String(32), default="today")
    relative_path: Mapped[str] = mapped_column(String(500))
    current_pointer: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")


class EventLog(TimestampMixin, Base):
    __tablename__ = "event_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    object_type: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (UniqueConstraint("source", "object_type", "object_id", "action", "summary", name="uq_event_signature"),)
