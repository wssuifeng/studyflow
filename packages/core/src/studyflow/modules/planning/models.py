from __future__ import annotations
from datetime import date, datetime, time
from typing import Optional
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from studyflow.infrastructure.persistence.base import Base, TimestampMixin


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
