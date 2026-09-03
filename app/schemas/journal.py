from __future__ import annotations

from datetime import date as DateType, time as TimeType
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.lesson_types import LessonType


Semester = Literal["autumn", "spring"]
LessonStatus = Literal["draft", "published", "cancelled"]
Attendance = Literal["present", "absent", "late", "excused"]


class JournalLessonCreate(BaseModel):
    group_id: int
    subject_id: int
    teacher_id: int | None = None
    date: DateType
    hours: int = Field(default=2, ge=1, le=24)
    starts_at: TimeType | None = None
    ends_at: TimeType | None = None
    type: LessonType | None = None
    topic_id: int | None = None
    topic_text: str | None = Field(default=None, max_length=500)
    comment: str | None = None
    status: LessonStatus = "published"
    schedule_lesson_id: int | None = None

    @field_validator("topic_text")
    @classmethod
    def normalize_topic_text(cls, value):
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def validate_times(self):
        if self.schedule_lesson_id is None and self.type is None:
            raise ValueError("type is required for a manual journal lesson")
        if self.topic_id is None and self.topic_text is None:
            raise ValueError("topic_id or topic_text is required")
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        return self


class JournalLessonPatch(BaseModel):
    version: int = Field(ge=1)
    date: DateType | None = None
    hours: int | None = Field(default=None, ge=1, le=24)
    starts_at: TimeType | None = None
    ends_at: TimeType | None = None
    type: LessonType | None = None
    topic_id: int | None = None
    topic_text: str | None = Field(default=None, max_length=500)
    comment: str | None = None
    status: LessonStatus | None = None

    @field_validator("topic_text")
    @classmethod
    def normalize_topic_text(cls, value):
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def validate_type(self):
        if "type" in self.model_fields_set and self.type is None:
            raise ValueError("type cannot be null")
        return self


class JournalEntryPut(BaseModel):
    attendance: Attendance = "present"
    grade: str | None = Field(default=None, max_length=16)
    comment: str | None = Field(default=None, max_length=2000)
    version: int = Field(default=0, ge=0)

    @field_validator("grade")
    @classmethod
    def normalize_grade(cls, value):
        if value is None:
            return None
        return value.strip().lower().replace("ё", "е") or None


class JournalBatchEntry(JournalEntryPut):
    student_id: int


class JournalBatchPut(BaseModel):
    entries: list[JournalBatchEntry] = Field(min_length=1, max_length=200)


class SubjectTopicCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    sort_order: int = Field(default=0, ge=0)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value):
        return value.strip()


class SubjectTopicPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value):
        return value.strip() if value is not None else None


class SubjectTopicsReorder(BaseModel):
    topic_ids: list[int] = Field(min_length=1)


class JournalAssignmentCreate(BaseModel):
    teacher_id: int
    group_id: int
    subject_id: int
    academic_year: int = Field(ge=2000, le=2200)
    semester: Semester


StudyComponent = Literal[
    "discipline",
    "interdisciplinary_course",
    "practice",
    "industrial_practice",
    "coursework",
]


class ControlPointsGenerate(BaseModel):
    group_id: int
    subject_id: int
    academic_year: int = Field(ge=2000, le=2200)
    semester: Semester
    total_practical_hours: int = Field(gt=0, le=2000)
    study_component: StudyComponent = "discipline"


class ControlPointPatch(BaseModel):
    version: int = Field(ge=1)
    planned_lesson_number: int | None = Field(default=None, gt=0)
    planned_hours: int | None = Field(default=None, gt=0)
    planned_date: DateType | None = None
    journal_lesson_id: int | None = None
    status: Literal["draft", "published", "locked"] | None = None


class ControlPointScorePut(BaseModel):
    current_score: float = Field(default=0, ge=0, le=20)
    project_score: float = Field(default=0, ge=0, le=20)
    attendance_score: float | None = Field(default=None, ge=0, le=4)
    comment: str | None = Field(default=None, max_length=2000)
    version: int = Field(default=0, ge=0)


class ControlPointBatchItem(ControlPointScorePut):
    student_id: int


class ControlPointBatchPut(BaseModel):
    scores: list[ControlPointBatchItem] = Field(min_length=1, max_length=200)
