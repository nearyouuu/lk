import os
from datetime import datetime

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
    material,
    news,
    profile,
    schedule,
    subject_type,
    testing,
)
from app.models.role import Role, user_roles
from app.models.schedule import Group, Lesson, Teacher
from app.models.user import User
from app.routers.schedules import update_lesson_topic
from app.schemas.schedule import LessonTopicUpdate


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_assigned_teacher_can_update_and_clear_lesson_topic():
    engine = _engine()
    with Session(engine) as db:
        teacher_role = Role(name="teacher")
        assigned_user = User(
            email="assigned@test.kz",
            password_hash="hash",
            full_name="Assigned Teacher",
        )
        other_user = User(
            email="other@test.kz",
            password_hash="hash",
            full_name="Other Teacher",
        )
        group = Group(code="TOPIC-1", title="Topic group")
        db.add_all([teacher_role, assigned_user, other_user, group])
        db.flush()
        db.execute(
            user_roles.insert(),
            [
                {"user_id": assigned_user.id, "role_id": teacher_role.id},
                {"user_id": other_user.id, "role_id": teacher_role.id},
            ],
        )
        assigned_teacher = Teacher(user_id=assigned_user.id, full_name="Assigned Teacher")
        other_teacher = Teacher(user_id=other_user.id, full_name="Other Teacher")
        db.add_all([assigned_teacher, other_teacher])
        db.flush()
        lesson = Lesson(
            group_id=group.id,
            teacher_id=assigned_teacher.id,
            lesson_number=1,
            starts_at=datetime(2026, 8, 20, 9, 0),
            ends_at=datetime(2026, 8, 20, 10, 30),
        )
        db.add(lesson)
        db.commit()

        result = update_lesson_topic(
            lesson.id,
            LessonTopicUpdate(topic="  Квадратные уравнения  "),
            db,
            assigned_user,
        )
        assert result == {"id": lesson.id, "topic": "Квадратные уравнения", "updated": True}
        assert db.get(Lesson, lesson.id).topic == "Квадратные уравнения"

        with pytest.raises(HTTPException) as exc_info:
            update_lesson_topic(
                lesson.id,
                LessonTopicUpdate(topic="Чужое изменение"),
                db,
                other_user,
            )
        assert exc_info.value.status_code == 403
        assert db.get(Lesson, lesson.id).topic == "Квадратные уравнения"

        cleared = update_lesson_topic(
            lesson.id,
            LessonTopicUpdate(topic="   "),
            db,
            assigned_user,
        )
        assert cleared["topic"] is None
        assert db.get(Lesson, lesson.id).topic is None
    engine.dispose()
