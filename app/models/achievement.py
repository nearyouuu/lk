from sqlalchemy import Column, Integer, String, ForeignKey, Text, Enum, Date, DateTime, func
from sqlalchemy.orm import relationship
import enum

from app.db.base import Base


class AchievementStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class AchievementType(str, enum.Enum):
    academic = "Учебные"
    sport = "Спортивные"
    creative = "Творческие"
    social = "Общественные"
    scientific = "Научные"


class Achievement(Base):
    __tablename__ = "achievements"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)

    description = Column(Text, nullable=False)
    image_path = Column(String, nullable=True)
    status = Column(Enum(AchievementStatus), default=AchievementStatus.pending, nullable=False)
    admin_message = Column(Text, nullable=True)
    type = Column(Enum(AchievementType), nullable=False, default=AchievementType.academic)

    event_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    points = Column(Integer, default=0)
    approved_by = Column(String, nullable=True)

    student = relationship("Student", back_populates="achievements")
