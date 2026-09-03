from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schedule import Subject, Teacher, teacher_subjects


def resolve_subject_teachers(db: Session, teacher_ids: list[int]) -> list[Teacher]:
    normalized_ids = list(dict.fromkeys(teacher_ids))
    if not normalized_ids:
        raise HTTPException(status_code=422, detail="teacher_ids must contain at least one teacher")
    teachers = db.scalars(
        select(Teacher).where(Teacher.id.in_(normalized_ids))
    ).all()
    by_id = {teacher.id: teacher for teacher in teachers}
    missing = [teacher_id for teacher_id in normalized_ids if teacher_id not in by_id]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"message": "Teacher not found", "teacher_ids": missing},
        )
    return [by_id[teacher_id] for teacher_id in normalized_ids]


def teacher_is_linked_to_subject(db: Session, teacher_id: int, subject_id: int) -> bool:
    return bool(
        db.scalar(
            select(teacher_subjects.c.teacher_id).where(
                teacher_subjects.c.teacher_id == teacher_id,
                teacher_subjects.c.subject_id == subject_id,
            )
        )
    )


def ensure_teacher_linked_to_subject(
    db: Session,
    teacher_id: int,
    subject_id: int,
    *,
    status_code: int = 422,
) -> None:
    if not teacher_is_linked_to_subject(db, teacher_id, subject_id):
        raise HTTPException(
            status_code=status_code,
            detail={
                "message": "Teacher is not linked to subject",
                "teacher_id": teacher_id,
                "subject_id": subject_id,
            },
        )


def subject_teacher_payload(subject: Subject) -> dict:
    teachers = sorted(subject.teachers, key=lambda teacher: teacher.id)
    return {
        "teacher_ids": [teacher.id for teacher in teachers],
        "teachers": [
            {"id": teacher.id, "full_name": teacher.full_name}
            for teacher in teachers
        ],
        "primary_teacher_id": subject.primary_teacher_id,
        "primary_teacher_name": (
            subject.primary_teacher.full_name if subject.primary_teacher else None
        ),
    }
