from sqlalchemy import ForeignKey,Integer,String,Text,Boolean,UniqueConstraint,Index
from sqlalchemy.orm import Mapped,mapped_column
from studyflow.infrastructure.persistence.base import Base,TimestampMixin
class EnglishErrorAggregate(TimestampMixin,Base):
    __tablename__="english_error_aggregates"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    notebook_id:Mapped[str]=mapped_column(ForeignKey("mistake_notebooks.id"))
    course_id:Mapped[str]=mapped_column(ForeignKey("courses.id"))
    exercise_key:Mapped[str]=mapped_column(String(200))
    rule_hash:Mapped[str]=mapped_column(String(64))
    objective_ids_json:Mapped[str]=mapped_column(Text,default="[]",server_default="[]")
    failed_attempts:Mapped[int]=mapped_column(Integer,default=0,server_default="0")
    failed_rounds:Mapped[int]=mapped_column(Integer,default=0,server_default="0")
    latest_attempt_id:Mapped[str|None]=mapped_column(ForeignKey("english_check_attempts.id"),nullable=True)
    version:Mapped[int]=mapped_column(Integer,default=1,server_default="1")
    archived:Mapped[bool]=mapped_column(Boolean,default=False,server_default="0")
    __table_args__=(UniqueConstraint("notebook_id","course_id","exercise_key","rule_hash",name="uq_en_aggregate"),Index("ix_en_aggregate_scope","notebook_id","course_id","archived","id"))
class EnglishErrorEvidence(TimestampMixin,Base):
    __tablename__="english_error_evidence"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    aggregate_id:Mapped[str]=mapped_column(ForeignKey("english_error_aggregates.id"))
    attempt_id:Mapped[str|None]=mapped_column(ForeignKey("english_check_attempts.id"),unique=True,nullable=True)
    feedback_id:Mapped[str|None]=mapped_column(ForeignKey("review_feedback.id"),unique=True,nullable=True)
    round_key:Mapped[str]=mapped_column(String(80))
    valid_error:Mapped[bool]=mapped_column(Boolean,default=True,server_default="1")
    __table_args__=(Index("ix_en_evidence_item","aggregate_id","round_key","id"),)
class EnglishReviewItem(TimestampMixin,Base):
    __tablename__="english_review_items"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    aggregate_id:Mapped[str]=mapped_column(ForeignKey("english_error_aggregates.id"),unique=True)
    reason:Mapped[str]=mapped_column(String(40))
    status:Mapped[str]=mapped_column(String(30),default="PENDING",server_default="PENDING")
    retest_task_id:Mapped[str|None]=mapped_column(ForeignKey("retest_tasks.id"),nullable=True)
