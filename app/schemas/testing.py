from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.models.testing import QuestionType, AttemptStatus


class TestShortOut(BaseModel):
    id: int
    title: str
    description: str | None
    deadline: datetime | None
    is_active: bool
    teacher_id: int | None
    group_ids: List[int]

    class Config:
        from_attributes = True

class RandomQuestionRule(BaseModel):
    type: QuestionType
    count: int

class TestRandomCreate(BaseModel):
    title: str
    description: str | None = None
    deadline: datetime | None = None
    teacher_id: int | None = None
    group_ids: List[int] = Field(default_factory=list)
    rules: List[RandomQuestionRule]

class TestImportCreate(BaseModel):
    title: str
    description: Optional[str] = None
    deadline: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    max_attempts: int = 1
    teacher_id: Optional[int] = None
    group_ids: List[int] = Field(default_factory=list)

    source: str = Field("manual", description="manual | excel")

    questions: Optional[List["QuestionCreate"]] = None

    excel_file_name: Optional[str] = None

class QuestionCreate(BaseModel):
    type: QuestionType
    text: str
    options: Optional[Any] = None
    correct_answers: Optional[Any] = None
    points: int = 1
    order_index: int = 0

class QuestionUpdate(BaseModel):
    id: Optional[int] = None
    type: Optional[QuestionType] = None
    text: Optional[str] = None
    options: Optional[Any] = None
    correct_answers: Optional[Any] = None
    points: Optional[int] = None
    order_index: Optional[int] = None



class TestCreate(BaseModel):
    title: str
    description: str | None = None
    duration_minutes: int | None = None
    max_attempts: int = 1
    deadline: datetime | None = None
    teacher_id: int | None = None
    group_ids: List[int] = Field(default_factory=list)
    questions: List[QuestionCreate]


class TestUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    duration_minutes: int | None = None
    max_attempts: int | None = None
    deadline: datetime | None = None
    is_active: bool | None = None
    teacher_id: int | None = None
    questions: list[QuestionUpdate] | None = None



class AssignGroupsIn(BaseModel):
    group_ids: List[int]


class QuestionOut(BaseModel):
    """Отображение вопроса для студентов и фронта — без правильных ответов"""
    id: int
    type: QuestionType
    text: str
    options: Any | None
    points: int
    order_index: int

    class Config:
        from_attributes = True


class QuestionAdminOut(QuestionOut):
    """Версия вопроса для преподавателей/админов — с правильными ответами"""
    correct_answers: Any | None = None


class TestOut(BaseModel):
    id: int
    title: str
    description: str | None
    duration_minutes: int | None
    max_attempts: int
    deadline: datetime | None
    is_active: bool
    teacher_id: int | None

    questions: List[QuestionOut]
    group_ids: List[int]

    total_points: int | None = None
    points_per_question: dict[int, int] | None = None
    attempts_summary: dict | None = None

    class Config:
        from_attributes = True




class TestAdminOut(TestOut):
    questions: List[QuestionAdminOut]


class StartOut(BaseModel):
    attempt_id: int
    attempt_number: int
    attempt_token: str
    started_at: datetime
    deadline_at: datetime | None = None
    must_finish_at: datetime | None = None


class SubmitIn(BaseModel):
    attempt_id: int
    attempt_token: str
    answers: Dict[str, Any]


class AttemptOut(BaseModel):
    id: int
    student_id: int
    test_id: int
    attempt_number: int
    status: AttemptStatus
    started_at: datetime
    finished_at: datetime | None
    auto_score: int | None
    teacher_score: int | None

    student_name: str | None = None
    group_name: str | None = None

    class Config:
        from_attributes = True



class AttemptDetailOut(AttemptOut):
    answers: Dict[str, Any] | None
    correct_answers: Dict[str, Any] | None = None

    detailed_scores: Dict[str, int] | None = None  
    total_score: int | None = None
    max_score: int | None = None

class ReviewIn(BaseModel):
    teacher_score: int
    comment: str | None = None
