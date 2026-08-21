import pandas as pd
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.schedule import Group, Subject, Teacher, Room, Lesson, LessonTime
from app.schemas.schedule import LessonCreate
from app.services.lesson_service import create_lesson


def get_lesson_time(db: Session, lesson_number: int):
    return db.scalar(
        select(LessonTime).where(LessonTime.lesson_number == lesson_number)
    )


def get_or_create(db: Session, model, defaults=None, **kwargs):
    instance = db.query(model).filter_by(**kwargs).first()
    if instance:
        return instance
    params = {**kwargs, **(defaults or {})}
    instance = model(**params)
    db.add(instance)
    db.flush()
    return instance


def detect_subject_type(subject_title: str) -> str | None:
    t = subject_title.lower()
    if "лаб" in t:
        return "lab"
    if "практика" in t or "практич" in t:
        return "practice"
    if "лекция" in t:
        return "lecture"
    return None


def parse_schedule_excel(file_path: str, db: Session) -> int:
    df = pd.read_excel(file_path)

    lessons_added = 0
    for _, row in df.iterrows():
        date = row["Дата"]
        lesson_number = row["№ пары"]
        group_code = str(row["Группа"]).strip()
        subject_title = str(row["Предмет"]).strip()
        teacher_name = str(row["Преподаватель"]).strip() if pd.notna(row["Преподаватель"]) else None
        room_code = str(row["Аудитория"]).strip() if pd.notna(row["Аудитория"]) else "Не указано"
        subject_type = detect_subject_type(str(row["Тип занятия"])) if pd.notna(row["Тип занятия"]) else None

        if pd.isna(date) or pd.isna(lesson_number) or not subject_title:
            continue

        date = pd.to_datetime(date, dayfirst=True).date()
        lesson_number = int(lesson_number)
        lt = get_lesson_time(db, lesson_number)
        if not lt:
            continue

        starts_at = datetime.combine(date, lt.start_time)
        ends_at = datetime.combine(date, lt.end_time)

        group = get_or_create(db, Group, code=group_code, defaults={"title": group_code})
        subject = get_or_create(db, Subject, title=subject_title)
        teacher = get_or_create(db, Teacher, full_name=teacher_name) if teacher_name else None
        room = get_or_create(db, Room, code=room_code, defaults={"title": room_code})

        payload = LessonCreate(
            group_code=group_code,
            room_code=room_code,
            starts_at=starts_at,
            ends_at=ends_at,
            subject_type=subject_type,
            notes=str(row.get("Комментарий")).strip() if pd.notna(row.get("Комментарий")) else None,
            subject_id=subject.id,
            teacher_id=teacher.id if teacher else None,
            subject_title=subject.title,
            teacher_full_name=teacher.full_name if teacher else None,
            lesson_number=lesson_number,
        )
        create_lesson(db, payload)
        lessons_added += 1

    db.commit()
    return lessons_added
