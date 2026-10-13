from sqlalchemy import ForeignKey,Text
from sqlalchemy.orm import Mapped,mapped_column
from studyflow.infrastructure.persistence.base import Base
class EnglishItem(Base):
    __tablename__="english_items"
    exercise_id:Mapped[str]=mapped_column(ForeignKey("exercises.id"),primary_key=True)
    spec_json:Mapped[str]=mapped_column(Text)
