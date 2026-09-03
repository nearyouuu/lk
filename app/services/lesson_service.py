from datetime import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schedule import Group, Lesson, LessonTime, Room, Subject, Teacher
from app.schemas.schedule import LessonCreate
from app.services.subject_service import resolve_subject
from app.services.subject_teacher_service import ensure_teacher_linked_to_subject


def get_or_create(db, model, where: dict, defaults: dict = {}):
    inst = db.scalar(select(model).filter_by(**where))
    if inst:
        return inst
    inst = model(**where, **defaults)
    db.add(inst)
    db.flush()
    return inst


def find_lesson_time(db: Session, lesson_clock: time):
    lesson_times = db.scalars(
        select(LessonTime).order_by(LessonTime.lesson_number)
    ).all()

    exact_match = next((lt for lt in lesson_times if lt.start_time == lesson_clock), None)
    if exact_match:
        return exact_match

    return next(
        (lt for lt in lesson_times if lt.start_time <= lesson_clock <= lt.end_time),
        None,
    )


def create_lesson(db: Session, payload: LessonCreate):
    group = db.scalar(select(Group).where(Group.code == payload.group_code))
    if not group:
        raise HTTPException(status_code=404, detail=f"Группа {payload.group_code} не найдена")

    room = db.scalar(select(Room).where(Room.code == payload.room_code))
    if not room:
        raise HTTPException(status_code=404, detail=f"Аудитория {payload.room_code} не найдена")

    if payload.subject_identifier or payload.subject_code or payload.subject_id:
        subject_id = resolve_subject(
            db,
            payload.subject_code,
            payload.subject_id,
            subject_identifier=payload.subject_identifier,
        ).id
    else:
        subject = get_or_create(db, Subject, {"title": payload.subject_title})
        subject_id = subject.id

    if payload.teacher_id:
        teacher_id = payload.teacher_id
    elif payload.teacher_full_name:
        teacher = get_or_create(
            db,
            Teacher,
            {"full_name": payload.teacher_full_name},
            {
                "email": payload.teacher_email,
                "phone": payload.teacher_phone,
                "subject": payload.teacher_subject,
            },
        )
        teacher_id = teacher.id
    else:
        teacher_id = None

    if teacher_id is not None:
        ensure_teacher_linked_to_subject(db, teacher_id, subject_id)

    if payload.lesson_number is not None:
        lt = db.scalar(select(LessonTime).where(LessonTime.lesson_number == payload.lesson_number))
        if not lt:
            raise HTTPException(status_code=400, detail=f"LessonTime {payload.lesson_number} не найден")
        lesson_number = payload.lesson_number
    else:
        lt = find_lesson_time(db, payload.starts_at.time())
        if not lt:
            raise HTTPException(
                status_code=400,
                detail=f"Не найден номер пары для {payload.starts_at.time()}",
            )
        lesson_number = lt.lesson_number

    starts_at = payload.starts_at.replace(hour=lt.start_time.hour, minute=lt.start_time.minute)
    ends_at = payload.ends_at.replace(hour=lt.end_time.hour, minute=lt.end_time.minute)

    lesson = Lesson(
        group_id=group.id,
        subject_id=subject_id,
        teacher_id=teacher_id,
        room_id=room.id,
        lesson_number=lesson_number,
        starts_at=starts_at,
        ends_at=ends_at,
        subject_type=payload.subject_type,
        topic=payload.topic,
        notes=payload.notes,
        created_by=None,
    )

    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return lesson
