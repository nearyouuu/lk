from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime
from enum import Enum


class AchievementStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class AchievementType(str, Enum):
    academic = "Учебные"
    sport = "Спортивные"
    creative = "Творческие"
    social = "Общественные"
    scientific = "Научные"


class AchievementBase(BaseModel):
    name: str
    description: str
    status: AchievementStatus = AchievementStatus.pending
    admin_message: Optional[str] = None
    type: AchievementType = AchievementType.academic
    event_date: Optional[date] = None
    points: Optional[int] = 0
    approved_by: Optional[str] = None


class AchievementCreate(AchievementBase):
    student_id: int


class AchievementUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[AchievementStatus] = None
    admin_message: Optional[str] = None
    type: Optional[AchievementType] = None
    event_date: Optional[date] = None
    points: Optional[int] = None
    approved_by: Optional[str] = None


class AchievementOut(AchievementBase):
    id: int
    student_id: int
    image_path: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True
