from __future__ import annotations
from datetime import date, datetime, time
from typing import Optional
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from studyflow.infrastructure.persistence.base import Base, TimestampMixin


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
