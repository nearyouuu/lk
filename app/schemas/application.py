from __future__ import annotations
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, field_validator

ApplicationType = Literal["certificate", "statement", "academic", "other"]
ApplicationStatus = Literal["new", "in_progress", "approved", "rejected"]

class ApplicationBase(BaseModel):
    type: ApplicationType = "certificate"
    title: str
    text: str

    @field_validator("title", "text")
    @classmethod
    def not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Поле не может быть пустым")
        return v

class ApplicationCreate(ApplicationBase):
    pass

class ApplicationUpdate(BaseModel):
    status: Optional[ApplicationStatus] = None
    comment: Optional[str] = None

class ApplicationOut(ApplicationBase):
    id: int
    student_id: int
    file_path: Optional[str] = None
    status: ApplicationStatus
    comment: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
