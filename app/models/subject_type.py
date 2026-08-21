from sqlalchemy import Column, Integer, String
from app.db.base import Base

class SubjectType(Base):
    __tablename__ = "subject_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
