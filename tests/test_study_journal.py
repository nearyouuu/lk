import os
from datetime import date, time

os.environ["DATABASE_URL"] = "sqlite://"

import pytest
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
from app.models.grade import Student
from app.models.journal import JournalEntry, JournalPeriod
from app.models.role import Permission, Role, role_permissions, user_roles
from app.models.schedule import Group, Subject, Teacher
from app.models.user import User
from app.routers.admin_journal import (
    create_journal_assignment,
    create_subject_topic,
    lock_journal_period,
)
from app.routers.journal import (
    create_journal_lesson,
    get_journal,
    put_journal_entries_batch,
    put_journal_entry,
)
from app.routers.control_points import (
    control_point_statement,
    generate_control_points,
    put_control_point_score,
)
from app.schemas.journal import (
    JournalAssignmentCreate,
    JournalBatchPut,
    JournalEntryPut,
    JournalLessonCreate,
    SubjectTopicCreate,
    ControlPointScorePut,
    ControlPointsGenerate,
)
from app.services.journal_service import JournalAPIError


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _fixture(db: Session):
    admin_role = Role(name="administrator")
    teacher_role = Role(name="teacher")
    admin = User(email="journal-admin@test.kz", password_hash="hash", full_name="Admin")
    teacher_user = User(
        email="journal-teacher@test.kz", password_hash="hash", full_name="Teacher"
    )
    group = Group(code="J-21", title="Journal group")
    subject = Subject(code="JOURNAL-01", title="Journal subject", grade_type="exam")
    db.add_all([admin_role, teacher_role, admin, teacher_user, group, subject])
    db.flush()
    db.execute(
        user_roles.insert(),
        [
            {"user_id": admin.id, "role_id": admin_role.id},
            {"user_id": teacher_user.id, "role_id": teacher_role.id},
        ],
    )
    for code in ("journal.read", "journal.lesson.write", "journal.entry.write"):
        permission = Permission(code=code, description=code)
        db.add(permission)
        db.flush()
        db.execute(
            role_permissions.insert().values(
                role_id=teacher_role.id, permission_id=permission.id
            )
        )
    teacher = Teacher(user_id=teacher_user.id, full_name="Teacher")
    db.add(teacher)
    students = []
    for index in range(2):
        student_user = User(
            email=f"journal-student-{index}@test.kz",
            password_hash="hash",
            full_name=f"Student {index}",
        )
        db.add(student_user)
        db.flush()
        student = Student(
            user_id=student_user.id,
            group_id=group.id,
            record_book=f"J-{index}",
        )
        db.add(student)
        students.append(student)
    db.commit()
    return admin, teacher_user, teacher, group, subject, students


def test_independent_journal_flow_and_period_lock():
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin, teacher_user, teacher, group, subject, students = _fixture(db)
        assignment = create_journal_assignment(
            JournalAssignmentCreate(
                teacher_id=teacher.id,
                group_id=group.id,
                subject_id=subject.id,
                academic_year=2026,
                semester="autumn",
            ),
            db,
            admin,
        )
        assert assignment["is_active"] is True

        topic = create_subject_topic(
            subject.id,
            SubjectTopicCreate(title="Independent topic", sort_order=0),
            db,
            admin,
        )
        lesson = create_journal_lesson(
            JournalLessonCreate(
                group_id=group.id,
                subject_id=subject.id,
                date=date(2026, 8, 24),
                starts_at=time(9, 0),
                ends_at=time(10, 30),
                type="practice",
                topic_id=topic["id"],
                status="published",
            ),
            "journal-idempotency-1",
            "req_test",
            db,
            teacher_user,
        )
        assert lesson["topic_text"] == "Independent topic"
        assert lesson["schedule_lesson_id"] is None

        payload = get_journal(
            group.id,
            subject.id,
            date(2026, 8, 1),
            date(2026, 12, 31),
            db,
            teacher_user,
        )
        assert len(payload["students"]) == 2
        assert len(payload["lessons"]) == 1

        saved = put_journal_entry(
            lesson["id"],
            students[0].id,
            JournalEntryPut(attendance="late", grade="4", comment="10 min", version=0),
            "req_entry",
            db,
            teacher_user,
        )
        assert saved["version"] == 1

        with pytest.raises(JournalAPIError) as conflict:
            put_journal_entry(
                lesson["id"],
                students[0].id,
                JournalEntryPut(attendance="present", grade="5", version=0),
                None,
                db,
                teacher_user,
            )
        assert conflict.value.status_code == 409

        period = db.get(JournalPeriod, payload["period"]["id"])
        lock_journal_period(period.id, db, admin)
        with pytest.raises(JournalAPIError) as locked:
            put_journal_entry(
                lesson["id"],
                students[0].id,
                JournalEntryPut(attendance="present", grade="5", version=1),
                None,
                db,
                teacher_user,
            )
        assert locked.value.status_code == 423
    engine.dispose()


def test_batch_save_has_partial_success():
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin, teacher_user, teacher, group, subject, students = _fixture(db)
        create_journal_assignment(
            JournalAssignmentCreate(
                teacher_id=teacher.id,
                group_id=group.id,
                subject_id=subject.id,
                academic_year=2026,
                semester="autumn",
            ),
            db,
            admin,
        )
        lesson = create_journal_lesson(
            JournalLessonCreate(
                group_id=group.id,
                subject_id=subject.id,
                date=date(2026, 9, 1),
                type="lecture",
                topic_text="Manual topic",
            ),
            None,
            None,
            db,
            teacher_user,
        )
        put_journal_entry(
            lesson["id"],
            students[0].id,
            JournalEntryPut(attendance="present", grade="5", version=0),
            None,
            db,
            teacher_user,
        )

        result = put_journal_entries_batch(
            lesson["id"],
            JournalBatchPut(
                entries=[
                    {
                        "student_id": students[0].id,
                        "attendance": "late",
                        "grade": "4",
                        "version": 0,
                    },
                    {
                        "student_id": students[1].id,
                        "attendance": "absent",
                        "grade": None,
                        "version": 0,
                    },
                ]
            ),
            None,
            db,
            teacher_user,
        )
        assert [row["student_id"] for row in result["updated"]] == [students[1].id]
        assert result["failed"][0]["code"] == "JOURNAL_VERSION_CONFLICT"
        assert db.query(JournalEntry).filter_by(lesson_id=lesson["id"]).count() == 2
    engine.dispose()


def test_control_points_formula_attendance_and_project_limit():
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin, teacher_user, teacher, group, subject, students = _fixture(db)
        create_journal_assignment(
            JournalAssignmentCreate(
                teacher_id=teacher.id,
                group_id=group.id,
                subject_id=subject.id,
                academic_year=2026,
                semester="autumn",
            ),
            db,
            admin,
        )
        lesson_ids = []
        for index in range(17):
            lesson = create_journal_lesson(
                JournalLessonCreate(
                    group_id=group.id,
                    subject_id=subject.id,
                    date=date(2026, 8, 1 + index),
                    starts_at=time(9, 0),
                    ends_at=time(13, 0),
                    type="practice",
                    topic_text=f"Topic {index + 1}",
                ),
                f"kt-lesson-{index}",
                None,
                db,
                teacher_user,
            )
            lesson_ids.append(lesson["id"])

        generated = generate_control_points(
            ControlPointsGenerate(
                group_id=group.id,
                subject_id=subject.id,
                academic_year=2026,
                semester="autumn",
                total_practical_hours=68,
                hours_per_lesson=4,
            ),
            None,
            db,
            teacher_user,
        )
        assert generated["lesson_count"] == 17
        assert generated["interval"] == 6
        assert [row["planned_lesson_number"] for row in generated["items"]] == [6, 12, 17]
        assert [row["base_max"] for row in generated["items"]] == [23.0, 23.0, 24.0]

        for index, lesson_id in enumerate(lesson_ids[:6]):
            put_journal_entry(
                lesson_id,
                students[0].id,
                JournalEntryPut(
                    attendance="absent" if index == 0 else "present",
                    version=0,
                ),
                None,
                db,
                teacher_user,
            )

        first_point = generated["items"][0]
        first_score = put_control_point_score(
            first_point["id"],
            students[0].id,
            ControlPointScorePut(
                current_score=18,
                project_score=15,
                attendance_score=None,
                version=1,
            ),
            None,
            db,
            teacher_user,
        )
        assert first_score["eligible_lessons"] == 6
        assert first_score["attended_lessons"] == 5
        assert first_score["attendance_score"] == 2.5
        assert first_score["total_score"] == 35.5

        second_point = generated["items"][1]
        with pytest.raises(JournalAPIError) as project_limit:
            put_control_point_score(
                second_point["id"],
                students[0].id,
                ControlPointScorePut(
                    current_score=20,
                    project_score=6,
                    attendance_score=None,
                    version=1,
                ),
                None,
                db,
                teacher_user,
            )
        assert project_limit.value.detail["error"]["code"] == "JOURNAL_PROJECT_SCORE_LIMIT"

        statement = control_point_statement(
            group.id,
            subject.id,
            2026,
            "autumn",
            db,
            teacher_user,
        )
        assert statement["maximums"] == {
            "current": 60,
            "attendance": 10,
            "project": 20,
            "semester_total": 90,
            "control_points": [23, 23, 24],
        }
        student_row = next(
            row for row in statement["items"] if row["student"]["id"] == students[0].id
        )
        assert student_row["semester_total"] == 35.5
    engine.dispose()


def test_control_points_are_rejected_for_industrial_practice():
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin, teacher_user, teacher, group, subject, _students = _fixture(db)
        create_journal_assignment(
            JournalAssignmentCreate(
                teacher_id=teacher.id,
                group_id=group.id,
                subject_id=subject.id,
                academic_year=2026,
                semester="autumn",
            ),
            db,
            admin,
        )
        with pytest.raises(JournalAPIError) as exc_info:
            generate_control_points(
                ControlPointsGenerate(
                    group_id=group.id,
                    subject_id=subject.id,
                    academic_year=2026,
                    semester="autumn",
                    total_practical_hours=68,
                    hours_per_lesson=4,
                    study_component="industrial_practice",
                ),
                None,
                db,
                teacher_user,
            )
        assert exc_info.value.detail["error"]["code"] == "JOURNAL_CONTROL_POINTS_NOT_APPLICABLE"
    engine.dispose()
