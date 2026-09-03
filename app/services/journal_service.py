from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, exists, select
from sqlalchemy.orm import Session

from app.models.grade import Student
from app.models.journal import (
    JournalAssignment,
    JournalAuditEvent,
    JournalEntry,
    JournalLesson,
    JournalPeriod,
)
from app.models.role import Permission, Role, role_permissions, user_roles
from app.models.schedule import Subject, Teacher
from app.models.user import User


class JournalAPIError(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict | None = None,
        request_id: str | None = None,
    ):
        super().__init__(
            status_code=status_code,
            detail={
                "error": {
                    "code": code,
                    "message": message,
                    "details": details or {},
                    "request_id": request_id or f"req_{uuid4().hex}",
                }
            },
        )


def error(status_code: int, code: str, message: str, details: dict | None = None):
    raise JournalAPIError(status_code, code, message, details)


def role_names(db: Session, user_id: int) -> set[str]:
    return set(
        db.scalars(
            select(Role.name)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == user_id)
        ).all()
    )


def is_privileged(db: Session, user: User) -> bool:
    return bool(role_names(db, user.id) & {"administrator", "director"})


def has_permission(db: Session, user: User, code: str) -> bool:
    if is_privileged(db, user):
        return True
    return bool(
        db.scalar(
            select(
                exists().where(
                    and_(
                        Permission.code == code,
                        role_permissions.c.permission_id == Permission.id,
                        user_roles.c.role_id == role_permissions.c.role_id,
                        user_roles.c.user_id == user.id,
                    )
                )
            )
        )
    )


def ensure_permission(db: Session, user: User, code: str):
    if not has_permission(db, user, code):
        error(403, "JOURNAL_ACCESS_DENIED", f"Нет права {code}")


def get_teacher(db: Session, user: User, required: bool = True) -> Teacher | None:
    teacher = db.scalar(select(Teacher).where(Teacher.user_id == user.id))
    if required and not teacher:
        error(403, "JOURNAL_TEACHER_PROFILE_REQUIRED", "Профиль преподавателя не найден")
    return teacher


def get_student(db: Session, user: User, required: bool = True) -> Student | None:
    student = db.scalar(select(Student).where(Student.user_id == user.id))
    if required and not student:
        error(403, "JOURNAL_STUDENT_PROFILE_REQUIRED", "Профиль студента не найден")
    return student


def period_bounds(academic_year: int, semester: str) -> tuple[date, date]:
    if semester == "autumn":
        return date(academic_year, 8, 1), date(academic_year + 1, 1, 31)
    if semester == "spring":
        return date(academic_year + 1, 2, 1), date(academic_year + 1, 7, 31)
    error(422, "JOURNAL_INVALID_SEMESTER", "Допустимы semester=autumn или semester=spring")


def period_key_for_date(value: date) -> tuple[int, str]:
    if value.month >= 8:
        return value.year, "autumn"
    if value.month == 1:
        return value.year - 1, "autumn"
    return value.year - 1, "spring"


def get_or_create_period(db: Session, academic_year: int, semester: str) -> JournalPeriod:
    period = db.scalar(
        select(JournalPeriod).where(
            JournalPeriod.academic_year == academic_year,
            JournalPeriod.semester == semester,
        )
    )
    if period:
        return period
    starts_on, ends_on = period_bounds(academic_year, semester)
    period = JournalPeriod(
        academic_year=academic_year,
        semester=semester,
        starts_on=starts_on,
        ends_on=ends_on,
    )
    db.add(period)
    db.flush()
    return period


def period_for_date(db: Session, value: date) -> JournalPeriod:
    academic_year, semester = period_key_for_date(value)
    return get_or_create_period(db, academic_year, semester)


def ensure_unlocked(period: JournalPeriod):
    if period.is_locked:
        error(
            423,
            "JOURNAL_PERIOD_LOCKED",
            "Период закрыт для редактирования",
            {"period_id": period.id},
        )


def teacher_has_assignment(
    db: Session,
    teacher_id: int,
    group_id: int,
    subject_id: int,
    academic_year: int,
    semester: str,
) -> bool:
    return bool(
        db.scalar(
            select(JournalAssignment.id).where(
                JournalAssignment.teacher_id == teacher_id,
                JournalAssignment.group_id == group_id,
                JournalAssignment.subject_id == subject_id,
                JournalAssignment.academic_year == academic_year,
                JournalAssignment.semester == semester,
                JournalAssignment.is_active.is_(True),
            )
        )
    )


def ensure_pair_access(
    db: Session,
    user: User,
    group_id: int,
    subject_id: int,
    academic_year: int,
    semester: str,
) -> Teacher | None:
    if is_privileged(db, user):
        return None
    teacher = get_teacher(db, user)
    if not teacher_has_assignment(
        db, teacher.id, group_id, subject_id, academic_year, semester
    ):
        error(403, "JOURNAL_ACCESS_DENIED", "Журнал не назначен текущему преподавателю")
    return teacher


def ensure_journal_read_access(
    db: Session,
    user: User,
    group_id: int,
    subject_id: int,
    academic_year: int,
    semester: str,
) -> Student | None:
    """Validate journal read access for staff users."""
    if not is_privileged(db, user) and get_teacher(db, user, required=False) is None:
        student = get_student(db, user, required=False)
        if student is not None:
            error(403, "JOURNAL_ACCESS_DENIED", "Студентам учебный журнал недоступен")
    ensure_pair_access(db, user, group_id, subject_id, academic_year, semester)
    return None


def ensure_lesson_access(db: Session, user: User, lesson: JournalLesson) -> Teacher | None:
    return ensure_pair_access(
        db,
        user,
        lesson.group_id,
        lesson.subject_id,
        lesson.period.academic_year,
        lesson.period.semester,
    )


def grade_scale(subject: Subject) -> str:
    return "pass_fail" if subject.grade_type == "зачет" else "five_point"


def validate_grade(subject: Subject, value: str | None):
    if value is None:
        return
    allowed = {"pass", "fail", "зачет", "не зачет"} if grade_scale(subject) == "pass_fail" else {"2", "3", "4", "5"}
    if value not in allowed:
        error(
            422,
            "JOURNAL_INVALID_GRADE",
            "Оценка не соответствует шкале дисциплины",
            {"grade_scale": grade_scale(subject), "allowed": sorted(allowed)},
        )


def student_full_name(student: Student) -> str:
    return student.user.full_name or student.user.email


def entry_state(entry: JournalEntry | None) -> dict | None:
    if entry is None:
        return None
    return {
        "attendance": entry.attendance,
        "grade": entry.grade,
        "comment": entry.comment,
        "version": entry.version,
    }


def lesson_state(lesson: JournalLesson | None) -> dict | None:
    if lesson is None:
        return None
    return {
        "date": lesson.lesson_date.isoformat(),
        "hours": lesson.hours,
        "starts_at": lesson.starts_at.isoformat() if lesson.starts_at else None,
        "ends_at": lesson.ends_at.isoformat() if lesson.ends_at else None,
        "type": lesson.lesson_type,
        "topic_id": lesson.topic_id,
        "topic_text": lesson.topic_text,
        "comment": lesson.comment,
        "status": lesson.status,
        "version": lesson.version,
    }


def add_audit(
    db: Session,
    user: User,
    entity: str,
    entity_id: int,
    operation: str,
    before: dict | None,
    after: dict | None,
    lesson_id: int | None = None,
    student_id: int | None = None,
    request_id: str | None = None,
):
    db.add(
        JournalAuditEvent(
            actor_id=user.id,
            entity=entity,
            entity_id=entity_id,
            lesson_id=lesson_id,
            student_id=student_id,
            operation=operation,
            before=before,
            after=after,
            request_id=request_id,
            created_at=datetime.now(timezone.utc),
        )
    )
