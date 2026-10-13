from sqlalchemy import ForeignKey,String,Boolean,UniqueConstraint,Integer,Index
from sqlalchemy.orm import Mapped,mapped_column
from studyflow.infrastructure.persistence.base import Base,TimestampMixin
class GeneralMistakeEntry(TimestampMixin,Base):
    __tablename__="general_mistake_entries"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    notebook_id:Mapped[str]=mapped_column(ForeignKey("mistake_notebooks.id"))
    course_id:Mapped[str]=mapped_column(ForeignKey("courses.id"))
    exercise_key:Mapped[str]=mapped_column(String(200))
    rule_hash:Mapped[str]=mapped_column(String(64))
    latest_feedback_id:Mapped[str]=mapped_column(ForeignKey("review_feedback.id"))
    status:Mapped[str]=mapped_column(String(32))
    version:Mapped[int]=mapped_column(Integer,default=1,server_default="1")
    archived:Mapped[bool]=mapped_column(Boolean,default=False,server_default="0")
    __table_args__=(UniqueConstraint("notebook_id","course_id","exercise_key","rule_hash",name="uq_general_mistake"),Index("ix_general_mistake_scope","notebook_id","course_id","archived","id"))
class GeneralMistakeOccurrence(TimestampMixin,Base):
    __tablename__="general_mistake_occurrences"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    entry_id:Mapped[str]=mapped_column(ForeignKey("general_mistake_entries.id"))
    feedback_id:Mapped[str]=mapped_column(ForeignKey("review_feedback.id"),unique=True)
