from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import SessionLocal, engine
from app.db.base import Base
from app.core.security import hash_password

from app.models.role import Role, Permission, role_permissions, user_roles
from app.models.user import User
from app.models.schedule import Group, Teacher, Room, Subject, LessonTime
from app.models.grade import Student
from app.models.news import News
from app.models.profile import AdminProfile, Director

PERMS = [
    "users:create", "users:read", "users:update", "users:delete",
    "roles:create", "roles:assign_permissions", "roles:assign_roles",
    "schedules:create", "schedules:read", "schedules:update", "schedules:delete",
    "grades:create", "grades:read", "grades:update", "grades:delete",
    "news:create", "news:read", "news:update", "news:delete",
    "audit:read",
]

ROLES = ["administrator", "director", "teacher", "student"]

def upsert_user_role(db: Session, user_id: int, role_id: int):
    stmt = (
        pg_insert(user_roles)
        .values(user_id=user_id, role_id=role_id)
        .on_conflict_do_nothing(index_elements=["user_id", "role_id"])
    )
    db.execute(stmt)

def upsert_role_perm(db: Session, role_id: int, perm_id: int):
    stmt = (
        pg_insert(role_permissions)
        .values(role_id=role_id, permission_id=perm_id)
        .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
    )
    db.execute(stmt)

def ensure(db: Session):
    existing_roles = {r.name for r in db.scalars(select(Role)).all()}
    for r in ROLES:
        if r not in existing_roles:
            db.add(Role(name=r, description=r.capitalize()))
    db.flush()

    existing_perms = {p.code for p in db.scalars(select(Permission)).all()}
    for p in PERMS:
        if p not in existing_perms:
            db.add(Permission(code=p, description=p))
    db.flush()

    roles = {r.name: r for r in db.scalars(select(Role)).all()}
    perms = {p.code: p for p in db.scalars(select(Permission)).all()}

    for _, perm in perms.items():
        upsert_role_perm(db, roles["administrator"].id, perm.id)
        upsert_role_perm(db, roles["director"].id, perm.id)

    for code, perm in perms.items():
        if code.endswith(":read"):
            upsert_role_perm(db, roles["teacher"].id, perm.id)
            upsert_role_perm(db, roles["student"].id, perm.id)
        if code.startswith("grades:") and code != "grades:delete":
            upsert_role_perm(db, roles["teacher"].id, perm.id)

    def ensure_user(email, pwd, full_name, role_name, **kwargs) -> User:
        u = db.scalar(select(User).where(User.email == email))
        if not u:
            u = User(
                email=email,
                password_hash=hash_password(pwd),
                full_name=full_name,
                is_active=True,
                phone=kwargs.get("phone"),
                avatar_url=kwargs.get("avatar_url"),
            )
            db.add(u)
            db.flush()
        upsert_user_role(db, u.id, roles[role_name].id)
        return u

    admin = ensure_user("admin@example.com", "Admin123!", "Администратор Системы", "administrator")
    director = ensure_user("director@example.com", "Director123!", "Иван Петров (Директор)", "director", phone="+70000000001")
    teacher_user = ensure_user("teacher@example.com", "Teacher123!", "Мария Сидорова (Преподаватель)", "teacher", phone="+70000000002")
    student_user = ensure_user("student@example.com", "Student123!", "Алексей Смирнов (Студент)", "student", phone="+70000000003")

    if not db.scalar(select(AdminProfile).where(AdminProfile.user_id == admin.id)):
        db.add(AdminProfile(user_id=admin.id, subject="Администрирование ЛК"))

    if not db.scalar(select(Director).where(Director.user_id == director.id)):
        db.add(Director(
            user_id=director.id,
            full_name=director.full_name,
            email=director.email,
            phone=director.phone,
            subject="Управление колледжем",
        ))

    teacher_profile = db.scalar(select(Teacher).where(Teacher.user_id == teacher_user.id))
    if not teacher_profile:
        teacher_profile = Teacher(
            user_id=teacher_user.id,
            full_name=teacher_user.full_name,
            email=teacher_user.email,
            phone=teacher_user.phone,
            subject="Математика"
        )
        db.add(teacher_profile)
        db.flush()

    abd_user = db.scalar(select(User).where(User.email == "abdelaal@donstu.ru"))
    if not abd_user:
        abd_user = User(
            email="abdelaal@donstu.ru",
            password_hash=hash_password("Abdelaal123!"),
            full_name="Абделаал Мохамед Эльсайед",
            is_active=True,
            phone="+70000001000",
        )
        db.add(abd_user); db.flush()

    upsert_user_role(db, abd_user.id, roles["student"].id)
    upsert_user_role(db, abd_user.id, roles["administrator"].id)

    abd_group = db.scalar(select(Group).where(Group.code == "МИ-25"))
    if not abd_group:
        abd_group = Group(code="МИ-25", title="Международные инженеры, набор 2025")
        db.add(abd_group); db.flush()

    if not db.scalar(select(Student).where(Student.user_id == abd_user.id)):
        db.add(Student(
            user_id=abd_user.id,
            group_id=abd_group.id,
            record_book="STU1001",
            insert_year="2025",
            course="1",
        ))

    group = db.scalar(select(Group).where(Group.code == "ИС-23"))
    if not group:
        group = Group(code="ИС-23", title="Информационные системы, 2023")
        db.add(group)
        db.flush()

    if not db.scalar(select(Student).where(Student.user_id == student_user.id)):
        db.add(Student(
            user_id=student_user.id,
            group_id=group.id,
            record_book="STU001",
            insert_year="2023",
            course="2",
        ))

    if not db.scalar(select(Room).where(Room.code == "A-101")):
        db.add(Room(code="A-101", title="Аудитория 101"))

    subject = db.scalar(select(Subject).where(Subject.title == "Алгебра"))
    if not subject:
        subject = Subject(title="Алгебра", code="ALG")
        db.add(subject)
        db.flush()

    if subject.primary_teacher_id != teacher_profile.id:
        subject.primary_teacher_id = teacher_profile.id

    if subject not in teacher_profile.subjects:
        teacher_profile.subjects.append(subject)

    if not db.scalar(select(News).limit(1)):
        db.add(News(
            title="Добро пожаловать!",
            body="Личный кабинет колледжей запущен.",
            author_id=admin.id,
            is_published=True,
        ))

    existing_times = db.scalars(select(LessonTime)).all()
    if not existing_times:
        from datetime import time
        lessons = [
            (1, time(8, 0),  time(9, 30)),
            (2, time(9, 40), time(11, 10)),
            (3, time(11, 20), time(12, 50)),
            (4, time(13, 30), time(15, 0)),
            (5, time(15, 10), time(16, 40)),
            (6, time(16, 50), time(18, 20)),
        ]
        for num, start, end in lessons:
            db.add(LessonTime(lesson_number=num, start_time=start, end_time=end))

def main():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure(db)
        db.commit()
    print("[seed] done.")

if __name__ == "__main__":
    main()
