import os
import sys
import tempfile
import types
import unittest
import zipfile
from datetime import datetime

import pandas as pd
from pydantic import ValidationError
from sqlalchemy import Text, create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import achievement, application, audit, document_order, material, news, subject_type, testing
from app.models.grade import Grade, Student
from app.models.role import Role
from app.models.schedule import Group, Room, Subject, Subdivision, Teacher
from app.models.subject_type import SubjectType
from app.models.user import User

# В минимальном CI-окружении passlib может отсутствовать; сам importer тестируем
# отдельно от уже существующей реализации password hashing.
try:
    import passlib  # noqa: F401
except ModuleNotFoundError:
    security_stub = types.ModuleType("app.core.security")
    security_stub.hash_password = lambda password: f"test-hash:{password}"
    security_stub.decode_token = lambda token, expected_type=None: {"sub": "1", "type": "access"}
    sys.modules["app.core.security"] = security_stub

# Router imports app.db.session; use an isolated SQLite URL in tests.
os.environ["DATABASE_URL"] = "sqlite://"

from app.services.user_importer import import_users_from_excel
from app.routers.grades import _excel_sheet_title, _semester_where, grated_router
from app.schemas.grade import FinalGradeIn, GradeCreate


class UserImporterTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all(Role(name=name) for name in ("student", "teacher", "director", "administrator"))
        self.db.commit()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _workbook(self, users, groups=None):
        path = os.path.join(self.temp_dir.name, "input.xlsx")
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            pd.DataFrame(users).to_excel(writer, sheet_name="Пользователи", index=False)
            if groups is not None:
                pd.DataFrame(groups).to_excel(writer, sheet_name="Группы", index=False)
        return path

    def _sheets_workbook(self, sheets):
        path = os.path.join(self.temp_dir.name, "catalogs.xlsx")
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for sheet_name, rows in sheets.items():
                pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)
        return path

    def test_imports_groups_students_and_teachers(self):
        path = self._workbook(
            [
                {"ФИО": "Студент Тест", "Электронная почта": "student@test.kz", "Роль": "студент", "Идентификатор группы": "G-001", "Номер зачётки": "001", "Курс": 2},
                {"ФИО": "Учитель Тест", "Электронная почта": "teacher@test.kz", "Роль": "преподаватель", "Предмет": "Математика"},
            ],
            [{"Идентификатор группы": "G-001", "Код группы": "ИС-24", "Название группы": "Информационные системы"}],
        )

        result = import_users_from_excel(self.db, path, self.temp_dir.name)

        self.assertEqual(result.created, 2)
        self.assertEqual(result.groups_created, 1)
        self.assertEqual(self.db.scalar(select(func.count(User.id))), 2)
        self.assertEqual(self.db.scalar(select(func.count(Student.id))), 1)
        self.assertEqual(self.db.scalar(select(func.count(Teacher.id))), 1)
        report = pd.read_excel(result.report_path, sheet_name="Пользователи")
        self.assertEqual(report["Статус"].tolist(), ["Создан", "Создан"])
        self.assertTrue(report["Пароль"].notna().all())

    def test_reports_bad_rows_without_aborting_valid_rows(self):
        path = self._workbook(
            [
                {"ФИО": "Без почты", "Электронная почта": "bad", "Роль": "студент", "Группа": "ИС-24"},
                {"ФИО": "Администратор", "Электронная почта": "admin@test.kz", "Роль": "администратор"},
                {"ФИО": "Дубль", "Электронная почта": "admin@test.kz", "Роль": "администратор"},
            ]
        )

        result = import_users_from_excel(self.db, path, self.temp_dir.name)

        self.assertEqual((result.created, result.failed), (1, 2))
        self.assertEqual(self.db.scalar(select(func.count(User.id))), 1)
        report = pd.read_excel(result.report_path, sheet_name="Пользователи")
        self.assertEqual(report["Статус"].tolist(), ["Ошибка", "Создан", "Ошибка"])

    def test_group_identifier_allows_duplicate_code_and_title(self):
        path = self._workbook(
            [
                {"ФИО": "Первый студент", "Электронная почта": "first@test.kz", "Роль": "студент", "Идентификатор группы": "G-101"},
                {"ФИО": "Второй студент", "Электронная почта": "second@test.kz", "Роль": "студент", "Идентификатор группы": "G-102"},
            ],
            [
                {"Идентификатор группы": "G-101", "Код группы": "ИС-24", "Название группы": "Информационные системы"},
                {"Идентификатор группы": "G-102", "Код группы": "ИС-24", "Название группы": "Информационные системы"},
            ],
        )

        result = import_users_from_excel(self.db, path, self.temp_dir.name)

        groups = self.db.scalars(select(Group).order_by(Group.identifier)).all()
        students = self.db.scalars(select(Student).order_by(Student.id)).all()
        self.assertEqual(result.groups_created, 2)
        self.assertEqual([group.identifier for group in groups], ["G-101", "G-102"])
        self.assertEqual([student.group_id for student in students], [groups[0].id, groups[1].id])

    def test_imports_teacher_with_long_subject_list(self):
        subject = "; ".join(f"Дисциплина {index}" for index in range(40))
        self.assertGreater(len(subject), 255)
        path = self._workbook(
            [
                {
                    "ФИО": "Преподаватель с длинным списком",
                    "Электронная почта": "long-subjects@test.kz",
                    "Роль": "преподаватель",
                    "Предмет": subject,
                }
            ]
        )

        result = import_users_from_excel(self.db, path, self.temp_dir.name)

        teacher = self.db.scalar(
            select(Teacher).where(Teacher.email == "long-subjects@test.kz")
        )
        self.assertEqual((result.created, result.failed), (1, 0))
        self.assertEqual(teacher.subject, subject)
        self.assertIsInstance(Teacher.__table__.c.subject.type, Text)

    def test_imports_subdivisions_rooms_subjects_and_teacher_links(self):
        path = self._sheets_workbook({
            "Подразделения": [
                {"Код подразделения": "UNI", "Название подразделения": "Университет", "Тип подразделения": "организация"},
                {"Код подразделения": "IT", "Название подразделения": "Кафедра ИТ", "Тип подразделения": "кафедра", "Код родительского подразделения": "UNI"},
            ],
            "Пользователи": [
                {"ФИО": "Преподаватель ИТ", "Электронная почта": "it.teacher@test.kz", "Роль": "преподаватель", "Подразделение": "IT"},
            ],
            "Аудитории": [
                {"Код аудитории": "A-101", "Название аудитории": "Компьютерный класс", "Вместимость": 24},
                {"Код аудитории": "BAD", "Название аудитории": "Ошибка", "Вместимость": 0},
            ],
            "Дисциплины": [
                {"Идентификатор дисциплины": "SUBJ-CS101", "Код дисциплины": "CS101", "Название дисциплины": "Основы программирования", "Тип дисциплины": "обязательная", "Email основного преподавателя": "it.teacher@test.kz", "Email преподавателей": "it.teacher@test.kz"},
            ],
        })

        result = import_users_from_excel(self.db, path, self.temp_dir.name)

        self.assertEqual(result.subdivisions_created, 2)
        self.assertEqual(result.rooms_created, 1)
        self.assertEqual(result.subjects_created, 1)
        self.assertEqual(result.subject_types_created, 1)
        self.assertEqual(result.failed, 1)
        child = self.db.scalar(select(Subdivision).where(Subdivision.code == "IT"))
        parent = self.db.scalar(select(Subdivision).where(Subdivision.code == "UNI"))
        self.assertEqual(child.parent_id, parent.id)
        teacher = self.db.scalar(select(Teacher).where(Teacher.email == "it.teacher@test.kz"))
        self.assertEqual(teacher.subdivision_id, child.id)
        subject = self.db.scalar(select(Subject).where(Subject.code == "CS101"))
        self.assertEqual(subject.primary_teacher_id, teacher.id)
        self.assertEqual([item.id for item in subject.teachers], [teacher.id])
        self.assertEqual(self.db.scalar(select(func.count(Room.id))), 1)
        self.assertEqual(self.db.scalar(select(func.count(SubjectType.id))), 1)

    def test_can_import_only_one_catalog_sheet(self):
        path = self._sheets_workbook({
            "Аудитории": [
                {"Код аудитории": "B-202", "Название аудитории": "Лекционная", "Вместимость": 80},
            ]
        })

        result = import_users_from_excel(self.db, path, self.temp_dir.name)

        self.assertEqual(result.rooms_created, 1)
        self.assertEqual(result.created, 0)
        self.assertEqual(self.db.scalar(select(func.count(Room.id))), 1)

    def test_subject_import_uses_identifier_and_allows_duplicate_code_and_title(self):
        self.db.add(Subject(identifier="SUBJ-OLD", code="SAME-101", title="Общее название", grade_type="exam"))
        self.db.commit()
        path = self._sheets_workbook({
            "Дисциплины": [
                {"Идентификатор дисциплины": "SUBJ-NEW", "Код дисциплины": "SAME-101", "Название дисциплины": "Общее название"},
                {"Идентификатор дисциплины": "SUBJ-OLD", "Код дисциплины": "OTHER-202", "Название дисциплины": "Другое название"},
            ]
        })

        result = import_users_from_excel(self.db, path, self.temp_dir.name)

        self.assertEqual(result.subjects_created, 1)
        created = self.db.scalar(select(Subject).where(Subject.identifier == "SUBJ-NEW"))
        self.assertIsNotNone(created)
        self.assertEqual((created.code, created.title), ("SAME-101", "Общее название"))
        self.assertEqual(self.db.scalar(select(func.count(Subject.id))), 2)

    def test_distributed_template_is_a_valid_xlsx(self):
        template = os.path.join("app", "static", "users_template.xlsx")
        self.assertTrue(zipfile.is_zipfile(template))
        workbook = pd.ExcelFile(template)
        self.assertEqual(
            workbook.sheet_names,
            ["Пользователи", "Группы", "Подразделения", "Аудитории", "Дисциплины", "Инструкция"],
        )
        subject_columns = pd.read_excel(template, sheet_name="Дисциплины", nrows=0).columns.tolist()
        self.assertEqual(subject_columns[0], "Идентификатор дисциплины")

    def test_semester_payload_is_normalized_and_stored_in_schema(self):
        payload = FinalGradeIn(
            student_id=1,
            subject_id=2,
            value="5",
            semester={"year": 2026, "season": " Весна "},
        )
        self.assertEqual(payload.semester.year, 2026)
        self.assertEqual(payload.semester.season, "весна")

    def test_grade_type_rejects_swagger_placeholder(self):
        with self.assertRaises(ValidationError):
            GradeCreate(
                student_id=4,
                lesson_id=1,
                grade_type="string",
                value="4",
                graded_at="2026-08-13T07:39:02.819Z",
                semester={"year": 2026, "season": "осень"},
            )

        payload = GradeCreate(
            student_id=4,
            lesson_id=1,
            grade_type=" Текущая ",
            value="4",
            graded_at="2026-08-13T07:39:02.819Z",
            semester={"year": 2026, "season": "осень"},
        )
        self.assertEqual(payload.grade_type, "текущая")

    def test_semester_filter_distinguishes_final_grades(self):
        self.db.add_all([
            Grade(student_id=1, subject_id=1, lesson_id=None, grade_type="final", value="4", graded_at=datetime.utcnow(), semester_year=2026, semester_season="весна"),
            Grade(student_id=1, subject_id=1, lesson_id=None, grade_type="final", value="5", graded_at=datetime.utcnow(), semester_year=2026, semester_season="осень"),
        ])
        self.db.commit()

        spring = self.db.scalars(select(Grade).where(_semester_where(2026, "весна"))).all()
        autumn = self.db.scalars(select(Grade).where(_semester_where(2026, "осень"))).all()
        self.assertEqual([grade.value for grade in spring], ["4"])
        self.assertEqual([grade.value for grade in autumn], ["5"])

    def test_grated_alias_exposes_create_and_final_routes(self):
        paths = {(route.path, tuple(route.methods)) for route in grated_router.routes}
        self.assertTrue(any(path == "/grated" and "POST" in methods for path, methods in paths))
        self.assertTrue(any(path == "/grated/final" and "POST" in methods for path, methods in paths))

    def test_export_sheet_title_is_safe_for_excel(self):
        self.assertEqual(_excel_sheet_title("ИТ/24:1"), "ИТ_24_1")
        self.assertEqual(len(_excel_sheet_title("А" * 40)), 31)


if __name__ == "__main__":
    unittest.main()
