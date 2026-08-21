from pydantic import BaseModel
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
    class Config:
        orm_mode = True
