from datetime import datetime
from sqlalchemy import (
    CheckConstraint, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True
    )
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    record_book: Mapped[str | None] = mapped_column(String(50), nullable=True)
    insert_year: Mapped[str | None] = mapped_column(String(10), nullable=True)
    course: Mapped[str | None] = mapped_column(String(10), nullable=True)

    user = relationship("User", back_populates="students", passive_deletes=True)
    group = relationship("Group", back_populates="students")

    achievements = relationship(
        "Achievement",
        back_populates="student",
        cascade="all, delete-orphan"
    )

    applications = relationship(
        "Application",
        back_populates="student",
        cascade="all, delete-orphan"
    )

    document_orders = relationship(
        "DocumentOrder",
        back_populates="student",
        cascade="all, delete-orphan"
    )

    attempts = relationship(
        "TestAttempt",
        back_populates="student",
        cascade="all, delete-orphan"
    )

    grades = relationship(
        "Grade",
        back_populates="student",
        cascade="all, delete-orphan"
    )


class Grade(Base):
    __tablename__ = "grades"
    __table_args__ = (
        UniqueConstraint("student_id", "lesson_id", "grade_type", name="uq_grade_per_lesson_type"),
        CheckConstraint(
            "semester_season IS NULL OR semester_season IN ('весна', 'осень')",
            name="ck_grades_semester_season",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"),
        index=True
    )

    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"),
        index=True,
        nullable=True
    )
    lesson_id: Mapped[int | None] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"),
        index=True,
        nullable=True
    )

    grade_type: Mapped[str] = mapped_column(String(30))
    value: Mapped[str] = mapped_column(String(10))
    graded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    semester_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    semester_season: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)

    modified_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )

    student = relationship("Student", back_populates="grades")
    subject = relationship("Subject")
    teacher = relationship("Teacher")
    lesson = relationship("Lesson")
    modified_by_admin = relationship("User", foreign_keys=[modified_by_admin_id])
