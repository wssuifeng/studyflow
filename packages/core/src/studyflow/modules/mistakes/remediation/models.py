"""Supplement provenance references immutable English evidence, not copied answers."""
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from studyflow.infrastructure.persistence.base import Base, TimestampMixin

class EnglishRemediationCourse(TimestampMixin, Base):
    __tablename__ = "english_remediation_courses"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    plan_line_id: Mapped[str] = mapped_column(ForeignKey("plan_lines.id"), index=True)
    objective_ids_json: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    provenance_hash: Mapped[str] = mapped_column(String(64))

class EnglishRemediationSource(TimestampMixin, Base):
    __tablename__ = "english_remediation_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("english_remediation_courses.course_id"), index=True)
    aggregate_id: Mapped[str] = mapped_column(ForeignKey("english_error_aggregates.id"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("english_error_evidence.id"))
    source_version: Mapped[int] = mapped_column(Integer)
    rule_hash: Mapped[str] = mapped_column(String(64))
    __table_args__=(UniqueConstraint("course_id","evidence_id",name="uq_remediation_evidence"),)
