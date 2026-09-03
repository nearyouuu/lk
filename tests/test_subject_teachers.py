import os
from datetime import datetime, time

os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (  # noqa: F401
    achievement,
    application,
    audit,
    document_order,
    grade,
    journal,
    material,
    news,
    profile,
    role,
    schedule,
    subject_type,
    testing,
    user,
)
from app.models.journal import JournalAssignment
from app.models.schedule import Group, LessonTime, Room, Teacher
from app.routers.admin import (
    admin_create_subject,
    admin_delete_teacher,
    admin_list_subjects,
    admin_update_subject,
)
from app.routers.schedules import teacher_teaching_overview
from app.schemas.admin import SubjectCreateIn
from app.schemas.schedule import LessonCreate
from app.services.lesson_service import create_lesson


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_subject_teacher_list_replaces_links_and_disables_removed_assignment():
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        teachers = [Teacher(full_name=f"Teacher {index}") for index in range(1, 4)]
        group = Group(code="ST-1", title="Subject teachers")
        db.add_all([*teachers, group])
        db.commit()

        created = admin_create_subject(
            SubjectCreateIn(
                title="Algorithms",
                subject_code="ALG-1",
                teacher_ids=[teachers[1].id, teachers[0].id, teachers[1].id],
                grade_type="exam",
            ),
            db,
        )
        assert created["teacher_ids"] == [teachers[0].id, teachers[1].id]
        assert created["primary_teacher_id"] == teachers[1].id
        assert [item["full_name"] for item in created["teachers"]] == [
            "Teacher 1",
            "Teacher 2",
        ]

        assignment = JournalAssignment(
            teacher_id=teachers[1].id,
            group_id=group.id,
            subject_id=created["id"],
            academic_year=2026,
            semester="autumn",
            is_active=True,
        )
        db.add(assignment)
        db.commit()

        updated = admin_update_subject(
            "ALG-1",
            SubjectCreateIn(
                title="Algorithms and data structures",
                subject_code="ALG-1",
                teacher_ids=[teachers[0].id, teachers[2].id],
                grade_type="exam",
            ),
            db,
        )
        assert updated["teacher_ids"] == [teachers[0].id, teachers[2].id]
        assert updated["primary_teacher_id"] == teachers[0].id
        assert db.get(JournalAssignment, assignment.id).is_active is False

        listed = admin_list_subjects(db, None)
        assert listed[0]["teacher_ids"] == updated["teacher_ids"]
        assert listed[0]["teachers"] == updated["teachers"]

        with pytest.raises(HTTPException) as missing_teacher:
            admin_update_subject(
                "ALG-1",
                SubjectCreateIn(
                    title="Algorithms and data structures",
                    subject_code="ALG-1",
                    teacher_ids=[999_999],
                    grade_type="exam",
                ),
                db,
            )
        assert missing_teacher.value.status_code == 422

        assert admin_delete_teacher(teachers[0].id, db) == {"ok": True}
        after_delete = admin_list_subjects(db, None)[0]
        assert after_delete["teacher_ids"] == [teachers[2].id]
        assert after_delete["primary_teacher_id"] == teachers[2].id
        with pytest.raises(HTTPException) as only_teacher:
            admin_delete_teacher(teachers[2].id, db)
        assert only_teacher.value.status_code == 409
    engine.dispose()


def test_schedule_accepts_any_linked_subject_teacher_and_rejects_unlinked_teacher():
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        linked_one = Teacher(full_name="Linked one")
        linked_two = Teacher(full_name="Linked two")
        unlinked = Teacher(full_name="Unlinked")
        group = Group(code="ST-2", title="Schedule group")
        room = Room(code="101", title="Room 101")
        lesson_time = LessonTime(
            lesson_number=1,
            start_time=time(9, 0),
            end_time=time(10, 30),
        )
        db.add_all([linked_one, linked_two, unlinked, group, room, lesson_time])
        db.commit()
        subject = admin_create_subject(
            SubjectCreateIn(
                title="Databases",
                subject_code="DB-1",
                teacher_ids=[linked_one.id, linked_two.id],
                grade_type="exam",
            ),
            db,
        )

        first_lesson = create_lesson(
            db,
            LessonCreate(
                group_code=group.code,
                room_code=room.code,
                subject_code=subject["subject_code"],
                teacher_id=linked_one.id,
                lesson_number=1,
                starts_at=datetime(2026, 9, 1, 9, 0),
                ends_at=datetime(2026, 9, 1, 10, 30),
                subject_type="lecture",
            ),
        )
        second_lesson = create_lesson(
            db,
            LessonCreate(
                group_code=group.code,
                room_code=room.code,
                subject_code=subject["subject_code"],
                teacher_id=linked_two.id,
                lesson_number=1,
                starts_at=datetime(2026, 9, 2, 9, 0),
                ends_at=datetime(2026, 9, 2, 10, 30),
                subject_type="practice",
            ),
        )
        assert first_lesson.teacher_id == linked_one.id
        assert second_lesson.teacher_id == linked_two.id

        overview = teacher_teaching_overview(linked_two.id, db, None, None)
        assert [item["id"] for item in overview["groups"]] == [group.id]
        assert overview["subjectsByGroup"][0]["subjects"][0]["id"] == subject["id"]

        with pytest.raises(HTTPException) as denied:
            create_lesson(
                db,
                LessonCreate(
                    group_code=group.code,
                    room_code=room.code,
                    subject_code=subject["subject_code"],
                    teacher_id=unlinked.id,
                    lesson_number=1,
                    starts_at=datetime(2026, 9, 3, 9, 0),
                    ends_at=datetime(2026, 9, 3, 10, 30),
                ),
            )
        assert denied.value.status_code == 422
    engine.dispose()
