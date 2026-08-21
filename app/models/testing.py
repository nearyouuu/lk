from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy import (
    Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Enum, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum
from app.db.base import Base

class QuestionType(str, enum.Enum):
    multi_choice = "multi_choice"
    choice = "choice"
    input = "input"
    long_input = "long_input"
    match = "match"

    @property
    def label(self) -> str:
        """Русское название типа вопроса"""
        mapping = {
            "multi_choice": "Несколько вариантов",
            "choice": "Один вариант",
            "input": "Краткий ответ",
            "long_input": "Развернутый ответ (эссе)",
            "match": "Сопоставление",
        }
        return mapping[self.value]

    @classmethod
    def from_label(cls, label: str) -> "QuestionType":
        """Преобразует русское название в enum"""
        reverse = {
            "несколько вариантов": cls.multi_choice,
            "один вариант": cls.choice,
            "краткий ответ": cls.input,
            "развернутый ответ (эссе)": cls.long_input,
            "эссе": cls.long_input,
            "сопоставление": cls.match,
        }
        key = label.strip().lower()
        return reverse.get(key, None)

class AttemptStatus(str, enum.Enum):
    started = "started"
    submitted = "submitted"
    reviewed = "reviewed"
    expired = "expired"

class Test(Base):
    __tablename__ = "tests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    questions = relationship("Question", back_populates="test", cascade="all, delete-orphan")
    groups = relationship("TestGroupAccess", back_populates="test", cascade="all, delete-orphan")
    attempts = relationship("TestAttempt", back_populates="test", cascade="all, delete-orphan")

class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id", ondelete="CASCADE"), index=True)
    type: Mapped[QuestionType] = mapped_column(Enum(QuestionType), nullable=False)
    text: Mapped[str] = mapped_column(Text)

    options: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    correct_answers: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)

    points: Mapped[int] = mapped_column(Integer, default=1)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    test = relationship("Test", back_populates="questions")

class TestGroupAccess(Base):
    __tablename__ = "test_group_access"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)

    test = relationship("Test", back_populates="groups")

    __table_args__ = (
        UniqueConstraint("test_id", "group_id", name="uq_test_group"),
    )

class TestAttempt(Base):
    __tablename__ = "test_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    test_id: Mapped[int] = mapped_column(
        ForeignKey("tests.id", ondelete="CASCADE"), index=True
    )

    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[AttemptStatus] = mapped_column(
        Enum(AttemptStatus), default=AttemptStatus.started
    )

    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    attempt_token: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    auto_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teacher_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    student = relationship("Student", back_populates="attempts")
    test = relationship("Test", back_populates="attempts")
