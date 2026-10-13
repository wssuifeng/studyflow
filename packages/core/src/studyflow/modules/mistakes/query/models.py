from sqlalchemy import ForeignKey,String,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from studyflow.infrastructure.persistence.base import Base,TimestampMixin
class MistakeNotebook(TimestampMixin,Base):
    __tablename__="mistake_notebooks"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    scope_key:Mapped[str]=mapped_column(String(80))
    plan_line_id:Mapped[str|None]=mapped_column(ForeignKey("plan_lines.id"),nullable=True)
    domain:Mapped[str]=mapped_column(String(20))
    __table_args__=(UniqueConstraint("scope_key","domain",name="uq_mistake_scope"),)
