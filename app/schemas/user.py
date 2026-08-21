from pydantic import BaseModel, EmailStr
from datetime import date, datetime
from typing import Optional, List

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    phone: str | None = None
    birth_date: date | None = None
    avatar_url: str | None = None
    role: str 

class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None
    is_active: bool
    last_login: datetime | None = None

class MeStudent(BaseModel):
    role: str = "student"
    fullName: str | None
    dateOfBirth: str | None
    photoUrl: str | None
    course: str | None
    email: str
    phoneNumber: str | None
    studyId: str | None
    group: str | None
    insertYear: str | None

class MeAdmin(BaseModel):
    role: str = "administrator"
    fullName: str | None
    photoUrl: str | None
    email: str
    subject: str | None

class StudentOut(BaseModel):
    id: int
    full_name: str
    email: str
    phone: str
    record_book: str
    course: str
    insert_year: str
    student_id: int

class StudentCreateIn(BaseModel):
    user_id: int
    group_id: int
    record_book: str | None = None
    insert_year: str | None = None
    course: str | None = None

class AdminTeacherUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    subject: Optional[str] = None
    subdivision_id: Optional[int] = None
    subject_ids: Optional[list[int]] = None
    subject_codes: Optional[list[str]] = None

class StudentUpdateIn(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    group_id: Optional[int] = None
    record_book: Optional[str] = None
    course: Optional[str] = None
    insert_year: Optional[str] = None

class MeDirector(BaseModel):
    role: str = "director"
    fullName: str | None
    email: str
    phoneNumber: str | None
    subject: str | None

class MeTeacher(BaseModel):
    role: str = "teacher"
    fullName: str | None
    email: str | None

class MeOut(BaseModel):
    id: int
    roles: list[str]
    student_id: Optional[int] = None
    teacher_id: Optional[int] = None
    profiles: list[MeAdmin | MeDirector | MeTeacher | MeStudent]
