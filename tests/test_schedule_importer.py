import os
import tempfile
from datetime import time

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import grade, schedule  # noqa: F401
from app.models.schedule import Lesson, LessonTime
from app.services.schedule_importer import parse_schedule_excel


def test_distributed_schedule_template_includes_topic_column():
    columns = pd.read_excel(os.path.join("app", "static", "example.xlsx"), nrows=0).columns
    assert "Тема занятия" in columns


def test_schedule_import_maps_topic_and_comment_to_separate_fields():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as db, tempfile.TemporaryDirectory() as temp_dir:
        db.add(
            LessonTime(
                lesson_number=1,
                start_time=time(9, 0),
                end_time=time(10, 30),
            )
        )
        db.commit()

        path = os.path.join(temp_dir, "schedule.xlsx")
        pd.DataFrame(
            [
                {
                    "Дата": "01.09.2026",
                    "№ пары": 1,
                    "Группа": "ТЕСТ-1",
                    "Предмет": "Математика",
                    "Преподаватель": "Иванов И.И.",
                    "Аудитория": "101",
                    "Тип занятия": "лекция",
                    "Тема занятия": "Квадратные уравнения",
                    "Комментарий": "Принести тетради",
                }
            ]
        ).to_excel(path, index=False)

        assert parse_schedule_excel(path, db) == 1

        lesson = db.scalar(select(Lesson))
        assert lesson.topic == "Квадратные уравнения"
        assert lesson.notes == "Принести тетради"

    engine.dispose()
