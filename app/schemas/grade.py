from pydantic import BaseModel, field_validator, model_validator
from datetime import datetime
from typing import Optional, List, Literal

GradeType =[
    "1", "2", "3", "4", "5", "Н", "Б", "О", "У", "н", "б", "о", "у"
]

GradeTypeFinal = [
    "1", "2", "3", "4", "5"
]


def _validate_grade_type(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or normalized == "string":
        raise ValueError("Укажите тип оценки, например «текущая» или «итог»")
    return normalized


class SemesterIn(BaseModel):
    year: int
    season: str

    @field_validator("year")
    @classmethod
    def validate_year(cls, value: int) -> int:
        if value < 2000 or value > 2200:
            raise ValueError("Год семестра должен быть в диапазоне 2000–2200")
        return value

    @field_validator("season")
    @classmethod
    def validate_season(cls, value: str) -> str:
        normalized = value.strip().lower().replace("ё", "е")
        if normalized not in {"весна", "осень"}:
            raise ValueError("Сезон семестра должен быть «весна» или «осень»")
        return normalized

class GradeCreate(BaseModel):
    student_id: int
    teacher_id: int | None = None
    lesson_id: int
    grade_type: str
    value: str
    graded_at: datetime
    comment: str | None = None
    semester: SemesterIn | None = None

    @field_validator("grade_type")
    @classmethod
    def validate_grade_type(cls, value: str) -> str:
        return _validate_grade_type(value)

class GradeUpdate(BaseModel):
    grade_type: Optional[str] = None
    value: Optional[str] = None
    comment: Optional[str] = None
    graded_at: Optional[datetime] = None
    subject_id: Optional[int] = None
    subject_code: Optional[str] = None
    lesson_id: Optional[int] = None
    teacher_id: Optional[int] = None

    @field_validator("grade_type")
    @classmethod
    def validate_grade_type(cls, value: str | None) -> str | None:
        return _validate_grade_type(value) if value is not None else None

class FinalGradeIn(BaseModel):
    student_id: int
    subject_code: str | None = None
    subject_id: int | None = None
    # Optional only for compatibility with clients deployed before this contract;
    # the backend still derives and validates the authoritative subject type.
    grade_type: Literal["exam", "зачет"] | None = None
    value: str
    comment: str | None = None
    semester: SemesterIn

    @model_validator(mode="after")
    def validate_subject_reference(self):
        if not self.subject_code and self.subject_id is None:
            raise ValueError("subject_code is required")
        return self

class GradeOut(BaseModel):
    id: int
    student_id: int
    subject_id: int
    subject_code: str | None = None
    teacher_id: int | None
    lesson_id: int | None
    grade_type: str
    value: str
    graded_at: datetime
    comment: str | None
    modified_by_admin_id: int | None = None
    semester: SemesterIn | None = None


class FinalGradePatch(BaseModel):
    grade_type: Literal["exam", "зачет"] | None = None
    value: str | None = None
    comment: str | None = None
    semester: SemesterIn | None = None
