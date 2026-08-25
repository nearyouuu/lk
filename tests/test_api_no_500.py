import os
import re
import sys
import types
from datetime import datetime, timezone

os.environ["DATABASE_URL"] = "sqlite://"

try:
    import passlib  # noqa: F401
except ModuleNotFoundError:
    import jwt

    security_stub = types.ModuleType("app.core.security")
    security_stub.hash_password = lambda password: f"test-hash:{password}"
    security_stub.verify_password = lambda plain, hashed: hashed == f"test-hash:{plain}"
    security_stub.create_access_token = lambda sub: jwt.encode(
        {"sub": sub, "type": "access"}, "devsecret", algorithm="HS256"
    )
    security_stub.create_refresh_token = lambda sub: jwt.encode(
        {"sub": sub, "type": "refresh"}, "devsecret", algorithm="HS256"
    )
    security_stub.decode_token = lambda token, expected_type=None: jwt.decode(
        token, "devsecret", algorithms=["HS256"]
    )
    sys.modules["app.core.security"] = security_stub

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core import deps
from app.core.deps import get_db
from app.core.security import create_access_token
from app.db.base import Base
from app.models import achievement, application, audit, document_order, material, news, profile, subject_type, testing
from app.models.audit import AuditLog
from app.models.application import Application
from app.models.document_order import DocumentOrder
from app.models.grade import Grade, Student
from app.models.news import News
from app.models.role import Role, user_roles
from app.models.schedule import Group, Lesson, Subject, Teacher
from app.models.testing import Test as ExamModel, TestAttempt as AttemptModel
from app.models.user import User
from app.routers import (
    achievement as achievement_router,
    admin,
    admin_schedule,
    admin_user_import,
    applications,
    auth,
    director,
    document_orders,
    grades,
    license as license_router,
    materials,
    me,
    news as news_router,
    ping,
    schedules,
    study,
    tests as tests_router,
    users,
    journal,
    admin_journal,
    control_points,
)
from app.routers.admin import admin_delete_user
from app.schemas.admin import SubjectCreateIn


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def test_delete_user_preserves_history_and_clears_optional_references():
    engine = _engine()
    with Session(engine) as db:
        target = User(email="delete@test.kz", password_hash="hash", full_name="Delete Me")
        owner = User(email="owner@test.kz", password_hash="hash", full_name="Owner")
        group = Group(code="SMOKE", title="Smoke group")
        db.add_all([target, owner, group])
        db.flush()

        student = Student(user_id=owner.id, group_id=group.id)
        target_student = Student(user_id=target.id, group_id=group.id)
        teacher = Teacher(user_id=target.id, full_name="Historical teacher")
        test = ExamModel(title="Historical test", created_by_id=target.id)
        db.add_all([student, target_student, teacher, test])
        db.flush()

        lesson = Lesson(
            group_id=group.id,
            lesson_number=1,
            starts_at=datetime(2026, 1, 1, 8, tzinfo=timezone.utc),
            ends_at=datetime(2026, 1, 1, 9, tzinfo=timezone.utc),
            created_by=target.id,
        )
        grade = Grade(
            student_id=student.id,
            grade_type="current",
            value="5",
            graded_at=datetime.now(timezone.utc),
            modified_by_admin_id=target.id,
        )
        attempt = AttemptModel(
            student_id=student.id,
            test_id=test.id,
            attempt_number=1,
            reviewed_by_user_id=target.id,
        )
        article = News(title="History", body="Must stay", author_id=target.id)
        log = AuditLog(
            user_id=target.id,
            method="POST",
            path="/admin/users/1/delete",
            status_code=200,
            created_at=datetime.now(timezone.utc),
        )
        application_row = Application(
            student_id=target_student.id,
            title="Delete with student",
            text="Cascade me",
        )
        document_order_row = DocumentOrder(
            student_id=target_student.id,
            full_name="Delete Me",
            order_location="ivanovo_medical_college",
            department="nursing",
            social_protection_information="nursing_9_full_time_first",
            study_form="full_time",
            group_name="SMOKE",
            certificate_type="education",
            scholarship_payment_period=None,
            custom_scholarship_payment_period=None,
            place_of_requirement="Test",
            copies_count=1,
        )
        db.add_all([
            lesson,
            grade,
            attempt,
            article,
            log,
            application_row,
            document_order_row,
        ])
        db.commit()
        target_id = target.id
        application_id = application_row.id
        document_order_id = document_order_row.id

        assert admin_delete_user(target_id, db) == {"ok": True}

        assert db.get(User, target_id) is None
        assert db.get(Teacher, teacher.id).user_id is None
        assert db.get(Lesson, lesson.id).created_by is None
        assert db.get(Grade, grade.id).modified_by_admin_id is None
        assert db.get(ExamModel, test.id).created_by_id is None
        assert db.get(AttemptModel, attempt.id).reviewed_by_user_id is None
        assert db.get(News, article.id).author_id is None
        assert db.get(AuditLog, log.id).user_id is None
        assert db.get(Application, application_id) is None
        assert db.get(DocumentOrder, document_order_id) is None
    engine.dispose()


def test_subject_duplicate_check_uses_only_code():
    engine = _engine()
    with Session(engine) as db:
        teacher = Teacher(full_name="Test Teacher")
        db.add(teacher)
        db.commit()

        first = admin.admin_create_subject(
            SubjectCreateIn(
                title="Одинаковое название",
                subject_code="SUBJ-001",
                teacher_id=teacher.id,
                grade_type="exam",
            ),
            db,
        )
        second = admin.admin_create_subject(
            SubjectCreateIn(
                title="Одинаковое название",
                subject_code="SUBJ-002",
                teacher_id=teacher.id,
                grade_type="exam",
            ),
            db,
        )

        assert first["id"] != second["id"]
        assert db.scalar(select(Subject).where(Subject.code == "SUBJ-002")) is not None

        try:
            admin.admin_create_subject(
                SubjectCreateIn(
                    title="Другое название",
                    subject_code="SUBJ-001",
                    teacher_id=teacher.id,
                    grade_type="exam",
                ),
                db,
            )
        except HTTPException as exc:
            assert exc.status_code == 400
            assert exc.detail == "Subject already exists"
        else:
            raise AssertionError("Duplicate subject code must be rejected")

        try:
            admin.admin_update_subject(
                "SUBJ-002",
                SubjectCreateIn(
                    title="Одинаковое название",
                    subject_code="SUBJ-001",
                    teacher_id=teacher.id,
                    grade_type="exam",
                ),
                db,
            )
        except HTTPException as exc:
            assert exc.status_code == 400
            assert exc.detail == "Subject already exists"
        else:
            raise AssertionError("Updating to a duplicate subject code must be rejected")
    engine.dispose()


def test_public_subject_contract_uses_subject_code():
    app = FastAPI()
    for router in (admin.router, schedules.router, grades.router, materials.router):
        app.include_router(router)

    schema = app.openapi()
    components = schema["components"]["schemas"]

    for component_name, field_name in (
        ("SubjectCreateIn", "subject_code"),
        ("LessonCreate", "subject_code"),
        ("LessonUpdate", "subject_code"),
        ("LessonOut", "subject_code"),
        ("FinalGradeIn", "subject_code"),
        ("GradeUpdate", "subject_code"),
        ("GradeOut", "subject_code"),
        ("TeacherCreateIn", "subject_codes"),
        ("TeacherSubjectsIn", "subject_codes"),
        ("AdminTeacherUpdate", "subject_codes"),
        ("MaterialOut", "subject_code"),
    ):
        assert field_name in components[component_name]["properties"]

    assert "/admin/subjects/{subject_code}/patch" in schema["paths"]
    assert "/admin/subjects/{subject_code}/delete" in schema["paths"]
    assert "/grades/final/{student_id}/{subject_code}" in schema["paths"]

    material_body = schema["paths"]["/materials/"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]
    material_component = material_body["$ref"].rsplit("/", 1)[-1]
    assert "subject_code" in components[material_component]["properties"]

    for path, method in (
        ("/schedules/lessons", "get"),
        ("/grades/export", "get"),
        ("/materials/my", "get"),
        ("/materials/by_group_subject", "get"),
        ("/materials/all", "get"),
    ):
        parameter_names = {
            parameter["name"] for parameter in schema["paths"][path][method].get("parameters", [])
        }
        assert "subject_code" in parameter_names


def test_every_documented_endpoint_returns_no_500():
    engine = _engine()
    db = Session(engine)
    admin_user = User(email="smoke-admin@test.kz", password_hash="hash", full_name="Smoke Admin")
    admin_role = Role(name="administrator")
    db.add_all([admin_user, admin_role])
    db.flush()
    db.execute(user_roles.insert().values(user_id=admin_user.id, role_id=admin_role.id))
    db.commit()

    app = FastAPI()
    for router in (
        ping.router,
        license_router.router,
        auth.router,
        me.router,
        users.router,
        admin.router,
        achievement_router.router,
        study.router,
        admin_schedule.router,
        admin_user_import.router,
        director.router,
        document_orders.router,
        materials.router,
        schedules.router,
        grades.router,
        grades.grated_router,
        tests_router.router,
        news_router.router,
        journal.router,
        admin_journal.router,
        control_points.router,
    ):
        app.include_router(router)

    def override_db():
        try:
            yield db
        finally:
            db.rollback()

    app.dependency_overrides[get_db] = override_db
    deps.has_feature = lambda _feature: (True, None)
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"Authorization": f"Bearer {create_access_token(str(admin_user.id))}"}
    schema = app.openapi()
    failures = []
    checked = 0

    for raw_path, operations in schema["paths"].items():
        path = re.sub(r"\{[^}]+\}", "999999", raw_path)
        for method, operation in operations.items():
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue

            params = {}
            for parameter in operation.get("parameters", []):
                if parameter.get("in") != "query" or not parameter.get("required"):
                    continue
                value_type = parameter.get("schema", {}).get("type")
                params[parameter["name"]] = 1 if value_type in {"integer", "number"} else "smoke"

            request_body = operation.get("requestBody", {}).get("content", {})
            kwargs = {"headers": headers, "params": params}
            if "application/json" in request_body:
                kwargs["json"] = {}
            elif "multipart/form-data" in request_body or "application/x-www-form-urlencoded" in request_body:
                kwargs["data"] = {}

            response = client.request(method.upper(), path, **kwargs)
            checked += 1
            if response.status_code == 500:
                failures.append(
                    f"{method.upper()} {raw_path}: {response.status_code} {response.text[:300]}"
                )

    assert checked >= 100, f"Only {checked} endpoints were discovered"
    assert failures == [], "Endpoints returning 5xx:\n" + "\n".join(failures)
    db.close()
    engine.dispose()
