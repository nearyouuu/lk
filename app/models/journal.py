from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SubjectTopic(Base):
    __tablename__ = "subject_topics"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="ck_subject_topics_sort_order"),
        Index("ix_subject_topics_subject_sort", "subject_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    subject = relationship("Subject")


class JournalPeriod(Base):
    __tablename__ = "journal_periods"
    __table_args__ = (
        UniqueConstraint("academic_year", "semester", name="uq_journal_period_year_semester"),
        CheckConstraint("semester IN ('autumn', 'spring')", name="ck_journal_period_semester"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    academic_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    semester: Mapped[str] = mapped_column(String(10), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class JournalAssignment(Base):
    """Назначение преподавателя группе и дисциплине, не зависящее от расписания."""

    __tablename__ = "journal_assignments"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id",
            "group_id",
            "subject_id",
            "academic_year",
            "semester",
            name="uq_journal_assignment",
        ),
        CheckConstraint("semester IN ('autumn', 'spring')", name="ck_journal_assignment_semester"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    academic_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    semester: Mapped[str] = mapped_column(String(10), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    teacher = relationship("Teacher")
    group = relationship("Group")
    subject = relationship("Subject")


class JournalLesson(Base):
    __tablename__ = "journal_lessons"
    __table_args__ = (
        CheckConstraint(
            "lesson_type IN ('lecture', 'practice', 'lab')",
            name="ck_journal_lessons_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'cancelled')",
            name="ck_journal_lessons_status",
        ),
        UniqueConstraint(
            "group_id",
            "subject_id",
            "lesson_date",
            "starts_at",
            name="uq_journal_lesson_slot",
        ),
        Index(
            "ix_journal_lessons_group_subject_date",
            "group_id",
            "subject_id",
            "lesson_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="RESTRICT"), nullable=False
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="RESTRICT"), nullable=False
    )
    period_id: Mapped[int] = mapped_column(
        ForeignKey("journal_periods.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    lesson_date: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    starts_at: Mapped[time | None] = mapped_column(Time, nullable=True)
    ends_at: Mapped[time | None] = mapped_column(Time, nullable=True)
    lesson_type: Mapped[str] = mapped_column(String(20), nullable=False)
    topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("subject_topics.id", ondelete="SET NULL"), nullable=True
    )
    topic_text: Mapped[str] = mapped_column(String(500), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    schedule_lesson_id: Mapped[int | None] = mapped_column(
        ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    group = relationship("Group")
    subject = relationship("Subject")
    teacher = relationship("Teacher")
    period = relationship("JournalPeriod")
    topic = relationship("SubjectTopic")
    schedule_lesson = relationship("Lesson")
    entries = relationship("JournalEntry", back_populates="lesson", cascade="all, delete-orphan")
    student_snapshots = relationship(
        "JournalLessonStudent", back_populates="lesson", cascade="all, delete-orphan"
    )


class JournalLessonStudent(Base):
    __tablename__ = "journal_lesson_students"
    __table_args__ = (
        UniqueConstraint("lesson_id", "student_id", name="uq_journal_lesson_student"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("journal_lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    record_book: Mapped[str | None] = mapped_column(String(50), nullable=True)

    lesson = relationship("JournalLesson", back_populates="student_snapshots")
    student = relationship("Student")


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("lesson_id", "student_id", name="uq_journal_entry_lesson_student"),
        CheckConstraint(
            "attendance IN ('present', 'absent', 'late', 'excused')",
            name="ck_journal_entries_attendance",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("journal_lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    attendance: Mapped[str] = mapped_column(String(20), nullable=False, default="present")
    grade: Mapped[str | None] = mapped_column(String(16), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    lesson = relationship("JournalLesson", back_populates="entries")
    student = relationship("Student")


class JournalAuditEvent(Base):
    __tablename__ = "journal_audit_events"
    __table_args__ = (
        Index("ix_journal_audit_entity", "entity", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entity: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    lesson_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_lessons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="SET NULL"), nullable=True, index=True
    )
    operation: Mapped[str] = mapped_column(String(30), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class JournalControlPoint(Base):
    __tablename__ = "journal_control_points"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "subject_id", "period_id", "number",
            name="uq_journal_control_point_number",
        ),
        CheckConstraint("number BETWEEN 1 AND 3", name="ck_journal_control_point_number"),
        CheckConstraint(
            "status IN ('draft', 'published', 'locked')",
            name="ck_journal_control_point_status",
        ),
        CheckConstraint("current_max = 20", name="ck_journal_control_point_current_max"),
        CheckConstraint("attendance_max IN (3, 4)", name="ck_journal_control_point_attendance_max"),
        Index(
            "ix_journal_control_points_group_subject_period",
            "group_id", "subject_id", "period_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    period_id: Mapped[int] = mapped_column(
        ForeignKey("journal_periods.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_lesson_number: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    journal_lesson_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_lessons.id", ondelete="SET NULL"), nullable=True
    )
    total_practical_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    hours_per_lesson: Mapped[int] = mapped_column(Integer, nullable=False)
    current_max: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("20")
    )
    attendance_max: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    project_semester_max: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("20")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    group = relationship("Group")
    subject = relationship("Subject")
    period = relationship("JournalPeriod")
    journal_lesson = relationship("JournalLesson")
    scores = relationship(
        "JournalControlPointScore", back_populates="control_point", cascade="all, delete-orphan"
    )


class JournalControlPointScore(Base):
    __tablename__ = "journal_control_point_scores"
    __table_args__ = (
        UniqueConstraint(
            "control_point_id", "student_id", name="uq_journal_control_point_student"
        ),
        CheckConstraint("current_score >= 0 AND current_score <= 20", name="ck_journal_cp_current_score"),
        CheckConstraint("project_score >= 0 AND project_score <= 20", name="ck_journal_cp_project_score"),
        CheckConstraint("attendance_score >= 0 AND attendance_score <= 4", name="ck_journal_cp_attendance_score"),
        CheckConstraint(
            "calculated_attendance_score >= 0 AND calculated_attendance_score <= 4",
            name="ck_journal_cp_calculated_attendance_score",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    control_point_id: Mapped[int] = mapped_column(
        ForeignKey("journal_control_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    current_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0")
    )
    attendance_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0")
    )
    calculated_attendance_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0")
    )
    attendance_is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    eligible_lessons: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attended_lessons: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    project_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0")
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    control_point = relationship("JournalControlPoint", back_populates="scores")
    student = relationship("Student")
