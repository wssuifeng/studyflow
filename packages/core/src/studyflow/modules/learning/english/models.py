from sqlalchemy import ForeignKey,Integer,String,Text,Boolean,Index
from sqlalchemy.orm import Mapped,mapped_column
from studyflow.infrastructure.persistence.base import Base,TimestampMixin
class EnglishStudyState(TimestampMixin,Base):
    __tablename__="english_study_states"
    study_session_id:Mapped[str]=mapped_column(ForeignKey("course_study_sessions.id"),primary_key=True)
    plan_line_id:Mapped[str|None]=mapped_column(ForeignKey("plan_lines.id"),nullable=True)
    position:Mapped[int]=mapped_column(Integer,default=0,server_default="0")
    version:Mapped[int]=mapped_column(Integer,default=1,server_default="1")
    completed:Mapped[bool]=mapped_column(Boolean,default=False,server_default="0")
class EnglishCheckAttempt(TimestampMixin,Base):
    __tablename__="english_check_attempts"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    study_session_id:Mapped[str]=mapped_column(ForeignKey("course_study_sessions.id"))
    exercise_id:Mapped[str]=mapped_column(ForeignKey("exercises.id"))
    submission_id:Mapped[str]=mapped_column(ForeignKey("submissions.id"))
    retest_task_id:Mapped[str|None]=mapped_column(ForeignKey("retest_tasks.id"),nullable=True)
    answer_text:Mapped[str]=mapped_column(Text)
    answer_version:Mapped[int]=mapped_column(Integer)
    rule_hash:Mapped[str]=mapped_column(String(64))
    result_json:Mapped[str]=mapped_column(Text)
    assisted:Mapped[bool]=mapped_column(Boolean,default=False,server_default="0")
    __table_args__=(Index("ix_en_check_scope","study_session_id","exercise_id","created_at","id"),)
class EnglishSubmissionDetail(Base):
    __tablename__="english_submission_details"
    submission_id:Mapped[str]=mapped_column(ForeignKey("submissions.id"),primary_key=True)
    last_attempt_id:Mapped[str|None]=mapped_column(ForeignKey("english_check_attempts.id"),nullable=True)
    assisted:Mapped[bool]=mapped_column(Boolean,default=False,server_default="0")
    skipped:Mapped[bool]=mapped_column(Boolean,default=False,server_default="0")
    evaluation_mode:Mapped[str]=mapped_column(String(20),default="local_exact",server_default="local_exact")
