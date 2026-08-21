from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
from typing import Optional, Literal

SubjectType = Literal["lecture", "practice", "lab"]

class LessonCreate(BaseModel):
    group_code: str
    room_code: str
    starts_at: datetime
    ends_at: datetime
    subject_type: Optional[SubjectType] = None
    topic: Optional[str] = None
    notes: Optional[str] = None

    subject_code: Optional[str] = None
    subject_id: Optional[int] = None
    teacher_id: Optional[int] = None

    subject_title: Optional[str] = None
    teacher_full_name: Optional[str] = None
    teacher_email: Optional[str] = None
    teacher_phone: Optional[str] = None
    teacher_subject: Optional[str] = None

    lesson_number: Optional[int] = None

    @field_validator("subject_code", "subject_title", mode="before")
    @classmethod
    def normalize_str(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("teacher_full_name", "teacher_email", "teacher_phone", "teacher_subject", mode="before")
    @classmethod
    def normalize_opt_str(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @model_validator(mode="after")
    def _check_subject(self):
        if not self.subject_code and self.subject_id is None and not self.subject_title:
            raise ValueError("subject_code is required")
        return self


class LessonTimeCreate(BaseModel):
    lesson_number: int
    start: str
    end: str

class LessonUpdate(BaseModel):
    group_code: Optional[str] = None
    subject_code: Optional[str] = None
    subject_id: Optional[int] = None
    subject_title: Optional[str] = None
    teacher_id: Optional[int] = None
    teacher_full_name: Optional[str] = None
    teacher_email: Optional[str] = None
    teacher_phone: Optional[str] = None
    teacher_subject: Optional[str] = None
    room_code: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    subject_type: Optional[SubjectType] = None
    topic: Optional[str] = None
    notes: Optional[str] = None
    lesson_number: Optional[int] = None


class LessonOut(BaseModel):
    id: int
    group: str
    subject: str
    subject_code: str | None = None
    teacher: Optional[str] = None
    room: Optional[str] = None
    starts_at: datetime
    ends_at: datetime
    subject_type: Optional[SubjectType] = None
    topic: Optional[str] = None
    notes: Optional[str] = None
    lesson_number: Optional[int] = None


class LessonTopicUpdate(BaseModel):
    topic: str | None = Field(default=None, max_length=1000)

    @field_validator("topic")
    @classmethod
    def normalize_topic(cls, value):
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
