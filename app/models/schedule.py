from datetime import datetime, time
from uuid import uuid4
from sqlalchemy import (
    Integer, String, DateTime, ForeignKey, Text,
    Table, Column, Time, CheckConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

teacher_subjects = Table(
    "teacher_subjects",
    Base.metadata,
    Column("teacher_id", ForeignKey("teachers.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
)


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identifier: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=lambda: str(uuid4())
    )
    code: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(255))

    students = relationship("Student", back_populates="group", cascade="all, delete-orphan")

class Subdivision(Base):
    """
    Подразделение: деканат, кафедра, отдел и т.д. (иерархия через parent_id).
    """
    __tablename__ = "subdivisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("subdivisions.id"), nullable=True)
    parent = relationship("Subdivision", remote_side="Subdivision.id", backref="children")

class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (
        CheckConstraint("grade_type IN ('exam', 'зачет')", name="ck_subjects_grade_type"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    grade_type: Mapped[str | None] = mapped_column(String(10), nullable=True)

    primary_teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"),
        index=True,
        nullable=True
    )
    primary_teacher = relationship("Teacher", foreign_keys=[primary_teacher_id])

    teachers = relationship(
        "Teacher", secondary=teacher_subjects, back_populates="subjects", order_by="Teacher.id"
    )

lesson_teachers = Table(
    "lesson_teachers",
    Base.metadata,
    Column("lesson_id", ForeignKey("lessons.id", ondelete="CASCADE"), primary_key=True),
    Column("teacher_id", ForeignKey("teachers.id", ondelete="CASCADE"), primary_key=True),
)

class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    subdivision_id: Mapped[int | None] = mapped_column(ForeignKey("subdivisions.id"), nullable=True)

    user = relationship("User")
    subdivision = relationship("Subdivision", backref="teachers")
    lessons = relationship("Lesson", secondary=lesson_teachers, back_populates="teachers")
    subjects = relationship("Subject", secondary=teacher_subjects, back_populates="teachers")


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (
        CheckConstraint(
            "subject_type IS NULL OR subject_type IN ('lecture', 'practice', 'lab')",
            name="ck_lessons_subject_type",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=True,
        index=True
)
    teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"),
        nullable=True
    )
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"),
        nullable=True
    )

    lesson_number: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    subject_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    group = relationship("Group")
    subject = relationship("Subject")
    teacher = relationship("Teacher")
    teachers = relationship("Teacher", secondary=lesson_teachers, back_populates="lessons")
    room = relationship("Room")


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)

class LessonTime(Base):
    __tablename__ = "lesson_times"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_number: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
