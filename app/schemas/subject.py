from pydantic import BaseModel, Field
from typing import Optional, Literal

class SubjectTypeBase(BaseModel):
    name: str

class SubjectTypeCreate(SubjectTypeBase):
    pass

class SubjectTypeUpdate(BaseModel):
    name: Optional[str] = None

class SubjectTypeOut(SubjectTypeBase):
    id: int
    class Config:
        orm_mode = True


class SubjectBase(BaseModel):
    title: str
    code: Optional[str] = None
    grade_type: Literal["exam", "зачет"]

class SubjectOut(SubjectBase):
    id: int
    teacher_ids: list[int] = Field(default_factory=list)
    teachers: list[dict] = Field(default_factory=list)
    primary_teacher_id: int | None = None
    primary_teacher_name: str | None = None

    class Config:
        orm_mode = True
