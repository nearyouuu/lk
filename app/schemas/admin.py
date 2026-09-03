from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from datetime import date, datetime
from typing import List, Optional, Literal

class AuditOut(BaseModel):
    id: int
    user_id: int | None
    method: str
    path: str
    query: str | None
    status_code: int
    ip: str | None
    user_agent: str | None
    created_at: datetime

class AdminUserUpdate(BaseModel):
    email: EmailStr | None = None
    phone: str | None = None
    full_name: str | None = None
    is_active: bool | None = None
    password: str | None = None

class AdminStudentUpdate(BaseModel):
    group_id: int | None = None
    record_book: str | None = None
    insert_year: str | None = None
    course: str | None = None

class AdminAssignRoles(BaseModel):
    roles: List[str]

class RoleCreateIn(BaseModel):
    name: str
    description: str | None = None

class PermissionCreateIn(BaseModel):
    code: str
    description: str | None = None

class RolePermissionAssignIn(BaseModel):
    permissions: List[str]

class GroupCreateIn(BaseModel):
    identifier: str
    code: str
    title: str

    @field_validator("identifier", "code", "title")
    @classmethod
    def normalize_group_fields(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field must not be empty")
        return value

class TeacherCreateIn(BaseModel):
    full_name: str
    email: str | None = None
    phone: str | None = None
    subject: str | None = None
    user_id: int | None = None
    subdivision_id: int | None = None
    subject_ids: List[int] | None = None
    subject_codes: List[str] | None = None

class TeacherSubjectsIn(BaseModel):
    subject_codes: List[str] | None = None
    subject_ids: List[int] | None = None

    @model_validator(mode="after")
    def validate_subjects(self):
        if self.subject_codes is None and self.subject_ids is None:
            raise ValueError("subject_codes is required")
        return self

class RoomCreateIn(BaseModel):
    code: str
    title: str
    capacity: int | None = None

class SubjectCreateIn(BaseModel):
    title: str
    subject_code: Optional[str] = None
    # Legacy alias for clients deployed before subject_code became canonical.
    code: Optional[str] = None
    teacher_ids: List[int] = Field(min_length=1)
    grade_type: Literal["exam", "зачет"]

    @field_validator("teacher_ids")
    @classmethod
    def normalize_teacher_ids(cls, value: List[int]) -> List[int]:
        return list(dict.fromkeys(value))

    @field_validator("title")
    @classmethod
    def normalize_subject_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Subject title must not be empty")
        return value

    @field_validator("subject_code", "code", mode="before")
    @classmethod
    def normalize_subject_code(cls, value):
        if not isinstance(value, str):
            return value
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_subject_code(self):
        if self.subject_code and self.code and self.subject_code != self.code:
            raise ValueError("subject_code and code must match")
        self.subject_code = self.subject_code or self.code
        if not self.subject_code:
            raise ValueError("subject_code is required")
        return self

class SubjectAssignTeacherIn(BaseModel):
    teacher_id: int

class SubdivisionCreateIn(BaseModel):
    name: str
    type: str | None = None
    code: str | None = None
    parent_id: int | None = None

class SubdivisionAssignTeachersIn(BaseModel):
    teacher_ids: List[int]

class AdminCreateUser(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    phone: str | None = None
    birth_date: date | None = None
    avatar_url: str | None = None
    roles: list[str]

    @field_validator("full_name", "phone", "avatar_url", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        return None if isinstance(v, str) and v.strip() == "" else v

    @field_validator("birth_date", mode="before")
    @classmethod
    def parse_birth_date(cls, v):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        if isinstance(v, date):
            return v
        return date.fromisoformat(v)
