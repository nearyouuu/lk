from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, delete, or_, func, text, update
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from datetime import date, datetime
from typing import List
import logging
import secrets, string

from app.core.deps import get_db, get_current_user, require_permission, is_admin, require_role_any, require_admin
from app.core.security import hash_password

from app.models.user import User
from app.models.role import Role, Permission, user_roles, role_permissions
from app.models.grade import Student
from app.models.profile import AdminProfile, Director
from app.models.schedule import Group, Teacher, Room, Subject, Subdivision, teacher_subjects
from app.models.audit import AuditLog
from app.models.schedule import Lesson
from app.models.journal import JournalAssignment
from app.schemas.schedule import LessonUpdate

from app.schemas.user import (MeAdmin, MeDirector, MeTeacher, MeStudent,
                              StudentUpdateIn, StudentCreateIn, AdminTeacherUpdate)
from app.schemas.admin import (
    AuditOut,
    AdminUserUpdate, AdminStudentUpdate,
    AdminCreateUser, AdminAssignRoles,
    RoleCreateIn, PermissionCreateIn, RolePermissionAssignIn,
    GroupCreateIn, TeacherCreateIn, TeacherSubjectsIn,
    RoomCreateIn, SubjectCreateIn, SubjectAssignTeacherIn,
    SubdivisionCreateIn, SubdivisionAssignTeachersIn,
)

from app.models.subject_type import SubjectType
from app.schemas.subject import SubjectTypeOut, SubjectTypeCreate, SubjectTypeUpdate
from app.services.subject_teacher_service import (
    ensure_teacher_linked_to_subject,
    resolve_subject_teachers,
    subject_teacher_payload,
)
from app.services.subject_service import resolve_subject


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

logger = logging.getLogger(__name__)

ROLE_ALIASES = {
    "admin": "administrator",
    "administrator": "administrator",
    "director": "director",
    "teacher": "teacher",
    "student": "student",
}

def _normalize_role(name: str) -> str:
    return ROLE_ALIASES.get(name.strip().lower(), name.strip().lower())


def _subjects_from_references(
    db: Session,
    subject_codes: list[str] | None,
    subject_ids: list[int] | None,
) -> list[Subject]:
    if subject_codes is not None:
        normalized_codes = list(dict.fromkeys(code.strip() for code in subject_codes if code.strip()))
        result: list[Subject] = []
        for code in normalized_codes:
            matches = db.scalars(
                select(Subject).where(Subject.code == code).order_by(Subject.id).limit(2)
            ).all()
            if not matches:
                raise HTTPException(status_code=404, detail="Subject not found")
            if len(matches) > 1:
                raise HTTPException(
                    status_code=409,
                    detail=f"Subject code '{code}' is ambiguous; use subject_ids",
                )
            result.append(matches[0])
        return result
    if subject_ids is not None:
        return list(db.scalars(select(Subject).where(Subject.id.in_(subject_ids))).all())
    return []


def _subject_from_path(db: Session, subject_identifier: str | int) -> Subject:
    """Resolve the stable identifier, with ID and unambiguous code fallbacks."""
    reference = str(subject_identifier).strip()
    subject = db.scalar(select(Subject).where(Subject.identifier == reference))
    if subject is None and reference.isdigit():
        subject = db.get(Subject, int(reference))
    if subject is None:
        matches = db.scalars(
            select(Subject).where(Subject.code == reference).order_by(Subject.id).limit(2)
        ).all()
        if len(matches) > 1:
            raise HTTPException(
                status_code=409,
                detail="Subject code is ambiguous; use subject identifier",
            )
        subject = matches[0] if matches else None
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return subject


def _subject_out(subject: Subject) -> dict:
    return {
        "id": subject.id,
        "identifier": subject.identifier,
        "title": subject.title,
        "code": subject.code,
        "subject_code": subject.code,
        "grade_type": subject.grade_type,
        **subject_teacher_payload(subject),
    }


def _set_subject_teachers(
    db: Session, subject: Subject, teacher_ids: list[int]
) -> None:
    teachers = resolve_subject_teachers(db, teacher_ids)
    removed_ids = {teacher.id for teacher in subject.teachers} - {
        teacher.id for teacher in teachers
    }
    subject.teachers = teachers
    subject.primary_teacher = teachers[0]
    if removed_ids and subject.id is not None:
        db.execute(
            update(JournalAssignment)
            .where(
                JournalAssignment.subject_id == subject.id,
                JournalAssignment.teacher_id.in_(removed_ids),
                JournalAssignment.is_active.is_(True),
            )
            .values(is_active=False)
        )


def _replace_teacher_subjects(
    teacher: Teacher, subjects: list[Subject]
) -> None:
    target_ids = {subject.id for subject in subjects}
    removed = [subject for subject in teacher.subjects if subject.id not in target_ids]
    orphaned = [subject.code or str(subject.id) for subject in removed if len(subject.teachers) == 1]
    if orphaned:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "A subject must have at least one teacher",
                "subjects": orphaned,
            },
        )

    teacher.subjects = subjects
    for subject in removed:
        if subject.primary_teacher_id == teacher.id:
            remaining = sorted(
                (item for item in subject.teachers if item.id != teacher.id),
                key=lambda item: item.id,
            )
            subject.primary_teacher = remaining[0]
    for subject in subjects:
        if subject.primary_teacher_id is None:
            subject.primary_teacher = teacher

@router.get("/users", dependencies=[Depends(require_permission("users:read"))])
def admin_list_users(
    db: Session = Depends(get_db),
    q: str | None = Query(None),
    role: str | None = Query(None),
    is_active: bool | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=12, le=500),
):
    offset = (page - 1) * limit

    stmt = select(User).distinct()

    if q:
        stmt = (
            stmt.join(user_roles, user_roles.c.user_id == User.id)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(
                or_(
                    User.full_name.ilike(f"%{q}%"),
                    User.email.ilike(f"%{q}%"),
                    Role.name.ilike(f"%{q}%"),
                )
            )
        )

    if role:
        if "join" not in str(stmt):
            stmt = (
                stmt.join(user_roles, user_roles.c.user_id == User.id)
                .join(Role, Role.id == user_roles.c.role_id)
            )
        stmt = stmt.where(Role.name == role)

    # ✅ сортировка по возрастанию ID (от раннего к последнему)
    stmt = stmt.order_by(User.id.asc())

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    users = db.execute(stmt.offset(offset).limit(limit)).scalars().all()
    if not users:
        return {
            "items": [],
            "pagination": {"total": 0, "page": page, "limit": limit, "totalPages": 0},
        }

    user_ids = [u.id for u in users]

    role_rows = (
        db.execute(
            select(user_roles.c.user_id, Role.name)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(user_roles.c.user_id.in_(user_ids))
        ).all()
    )
    roles_map: dict[int, list[str]] = {uid: [] for uid in user_ids}
    for uid, rname in role_rows:
        roles_map.setdefault(uid, []).append(rname)

    profiles_map: dict[int, list[dict]] = {uid: [] for uid in user_ids}
    student_ids: dict[int, int] = {}
    teacher_ids: dict[int, int] = {}

    for adm, u in db.execute(
        select(AdminProfile, User)
        .join(User, User.id == AdminProfile.user_id)
        .where(AdminProfile.user_id.in_(user_ids))
    ):
        profiles_map[adm.user_id].append(
            {
                "role": "administrator",
                "fullName": u.full_name,
                "dateOfBirth": u.birth_date.isoformat() if u.birth_date else None,
                "photoUrl": u.avatar_url,
                "course": None,
                "email": u.email,
                "phoneNumber": u.phone,
                "studyId": None,
                "group": None,
                "insertYear": None,
                "subject": adm.subject,
            }
        )

    for d, u in db.execute(
        select(Director, User)
        .join(User, User.id == Director.user_id)
        .where(Director.user_id.in_(user_ids))
    ):
        profiles_map[d.user_id].append(
            {
                "role": "director",
                "fullName": d.full_name or u.full_name,
                "dateOfBirth": u.birth_date.isoformat() if u.birth_date else None,
                "photoUrl": u.avatar_url,
                "course": None,
                "email": d.email or u.email,
                "phoneNumber": d.phone or u.phone,
                "studyId": None,
                "group": None,
                "insertYear": None,
                "subject": d.subject,
            }
        )

    for t, u in db.execute(
        select(Teacher, User)
        .join(User, User.id == Teacher.user_id)
        .where(Teacher.user_id.in_(user_ids))
    ):
        profiles_map[t.user_id].append(
            {
                "role": "teacher",
                "fullName": t.full_name or u.full_name,
                "dateOfBirth": u.birth_date.isoformat() if u.birth_date else None,
                "photoUrl": u.avatar_url,
                "course": None,
                "email": t.email or u.email,
                "phoneNumber": t.phone or u.phone,
                "studyId": None,
                "group": None,
                "insertYear": None,
                "subject": t.subject,
            }
        )
        teacher_ids[t.user_id] = t.id

    for s, u, g in db.execute(
        select(Student, User, Group)
        .join(User, User.id == Student.user_id)
        .join(Group, Group.id == Student.group_id)
        .where(Student.user_id.in_(user_ids))
    ):
        profiles_map[s.user_id].append(
            {
                "role": "student",
                "fullName": u.full_name,
                "dateOfBirth": u.birth_date.isoformat() if u.birth_date else None,
                "photoUrl": u.avatar_url,
                "course": s.course,
                "email": u.email,
                "phoneNumber": u.phone,
                "studyId": s.record_book,
                "group": g.code if g else None,
                "groupId": g.id if g else None,
                "groupIdentifier": g.identifier if g else None,
                "insertYear": s.insert_year,
                "subject": None,
            }
        )
        student_ids[s.user_id] = s.id

    total_pages = (total + limit - 1) // limit if total else 0

    return {
        "items": [
            {
                "id": u.id,
                "email": u.email,
                "phone": u.phone,
                "full_name": u.full_name,
                "is_active": u.is_active,
                "last_login": u.last_login,
                "roles": roles_map.get(u.id, []),
                "student_id": student_ids.get(u.id),
                "teacher_id": teacher_ids.get(u.id),
                "profiles": profiles_map.get(u.id, []),
            }
            for u in users
        ],
        "pagination": {
            "total": total,
            "page": page,
            "limit": limit,
            "totalPages": total_pages,
        },
    }

@router.post("/users/{user_id}/avatar", dependencies=[Depends(require_permission("users:update"))])
def admin_update_user_avatar(
    user_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    from app.core.files import save_avatar_file, delete_file_if_local
    rel = save_avatar_file(user.id, file)

    delete_file_if_local(user.avatar_url)
    user.avatar_url = rel
    db.commit()

    from app.core.config import settings
    return {
        "user_id": user.id,
        "avatar_path": rel,
        "avatar_url": f"{settings.MEDIA_URL}/{rel}",
    }

@router.get("/audit", dependencies=[Depends(require_permission("audit:read"))])
def admin_audit_list(
    db: Session = Depends(get_db),
    user_id: int | None = Query(None),
    path: str | None = Query(None),
    method: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    q = select(AuditLog).order_by(AuditLog.created_at.desc())
    if user_id is not None: q = q.where(AuditLog.user_id == user_id)
    if path: q = q.where(AuditLog.path.ilike(f"%{path}%"))
    if method: q = q.where(AuditLog.method == method.upper())
    if date_from: q = q.where(AuditLog.created_at >= date_from)
    if date_to: q = q.where(AuditLog.created_at < date_to)
    rows = db.execute(q.offset(offset).limit(limit)).scalars().all()
    return [
        {
            "id": r.id, "user_id": r.user_id, "method": r.method, "path": r.path,
            "query": r.query, "status_code": r.status_code, "ip": r.ip,
            "user_agent": r.user_agent, "created_at": r.created_at
        } for r in rows
    ]

@router.post("/users", dependencies=[Depends(require_permission("users:create"))])
def admin_create_user(payload: AdminCreateUser, me=Depends(get_current_user), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=400, detail="Email already exists")
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        phone=payload.phone,
        birth_date=payload.birth_date,
        avatar_url=payload.avatar_url,
        is_active=True,
    )
    db.add(user); db.flush()
    for rname in payload.roles:
        r = db.scalar(select(Role).where(Role.name == _normalize_role(rname)))
        if not r:
            raise HTTPException(status_code=400, detail=f"Role not found: {rname}")
        db.execute(user_roles.insert().values(user_id=user.id, role_id=r.id))
    db.commit()
    return {"id": user.id, "email": user.email, "roles": payload.roles}

def generate_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

@router.post("/users/{user_id}/patch", dependencies=[Depends(require_permission("users:update"))])
def admin_update_user(user_id: int, payload: AdminUserUpdate, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.email is not None: u.email = payload.email
    if payload.phone is not None: u.phone = payload.phone
    if payload.full_name is not None: u.full_name = payload.full_name
    if payload.is_active is not None: u.is_active = payload.is_active
    if payload.password:
        u.password_hash = hash_password(payload.password)

    db.commit(); db.refresh(u)
    return {
        "id": u.id, "email": u.email, "phone": u.phone, "full_name": u.full_name,
        "is_active": u.is_active
    }

@router.post("/users/{user_id}/delete", dependencies=[Depends(require_permission("users:delete"))])
def admin_delete_user(user_id: int, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        db.delete(u)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint_name = getattr(getattr(exc, "orig", None), "diag", None)
        constraint_name = getattr(constraint_name, "constraint_name", None)
        logger.exception(
            "Cannot delete user %s because constraint %s still references it",
            user_id,
            constraint_name or "unknown",
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "User cannot be deleted because related records still reference it"
                + (f" (constraint: {constraint_name})" if constraint_name else "")
            ),
        ) from exc
    return {"ok": True}

@router.post("/users/{user_id}/roles", dependencies=[Depends(require_permission("roles:assign_roles"))])
def admin_assign_roles(user_id: int, payload: AdminAssignRoles, me=Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    db.execute(delete(user_roles).where(user_roles.c.user_id == user_id))
    for name in payload.roles:
        r = db.scalar(select(Role).where(Role.name == _normalize_role(name)))
        if not r:
            raise HTTPException(status_code=400, detail=f"Role not found: {name}")
        db.execute(user_roles.insert().values(user_id=user_id, role_id=r.id))
    db.commit()
    return {"user_id": user_id, "roles": payload.roles}

@router.post("/roles", dependencies=[Depends(require_permission("roles:create"))])
def admin_create_role(payload: RoleCreateIn, db: Session = Depends(get_db)):
    if db.scalar(select(Role).where(Role.name == payload.name)):
        raise HTTPException(status_code=400, detail="Role already exists")
    role = Role(name=payload.name, description=payload.description)
    db.add(role); db.commit()
    return {"id": role.id, "name": role.name}

@router.get("/roles", dependencies=[Depends(require_permission("roles:create"))])
def admin_list_roles(db: Session = Depends(get_db)):
    rows = db.scalars(select(Role)).all()
    return [{"id": r.id, "name": r.name, "description": r.description} for r in rows]

@router.post("/permissions", dependencies=[Depends(require_permission("roles:assign_permissions"))])
def admin_create_permission(payload: PermissionCreateIn, db: Session = Depends(get_db)):
    if db.scalar(select(Permission).where(Permission.code == payload.code)):
        raise HTTPException(status_code=400, detail="Permission already exists")
    p = Permission(code=payload.code, description=payload.description)
    db.add(p); db.commit()
    return {"id": p.id, "code": p.code}

@router.get("/permissions", dependencies=[Depends(require_permission("roles:assign_permissions"))])
def admin_list_permissions(db: Session = Depends(get_db)):
    rows = db.scalars(select(Permission)).all()
    return [{"id": p.id, "code": p.code, "description": p.description} for p in rows]

@router.post("/roles/{role_id}/permissions", dependencies=[Depends(require_permission("roles:assign_permissions"))])
def admin_grant_permissions(role_id: int, payload: RolePermissionAssignIn, db: Session = Depends(get_db)):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    for code in payload.permissions:
        p = db.scalar(select(Permission).where(Permission.code == code))
        if not p:
            p = Permission(code=code, description=code)
            db.add(p); db.flush()
        db.execute(role_permissions.insert().values(role_id=role_id, permission_id=p.id))
    db.commit()
    return {"role_id": role_id, "granted": payload.permissions}

@router.post("/roles/{role_id}/permissions/{code}", dependencies=[Depends(require_permission("roles:assign_permissions"))])
def admin_revoke_permission(role_id: int, code: str, db: Session = Depends(get_db)):
    p = db.scalar(select(Permission).where(Permission.code == code))
    if not p:
        raise HTTPException(status_code=404, detail="Permission not found")
    db.execute(
        delete(role_permissions).where(
            role_permissions.c.role_id == role_id,
            role_permissions.c.permission_id == p.id
        )
    )
    db.commit()
    return {"role_id": role_id, "revoked": code}


@router.post("/students", dependencies=[Depends(require_permission("users:create"))])
def admin_create_student(payload: StudentCreateIn, db: Session = Depends(get_db)):
    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if db.scalar(select(Student).where(Student.user_id == payload.user_id)):
        raise HTTPException(status_code=400, detail="This user is already a student")
    group = db.get(Group, payload.group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    student_role = db.scalar(select(Role).where(Role.name == "student"))
    if not student_role:
        raise HTTPException(status_code=500, detail="Role 'student' not found")
    has_student_role = db.scalar(
        select(user_roles.c.user_id).where(
            user_roles.c.user_id == user.id,
            user_roles.c.role_id == student_role.id
        )
    )
    if not has_student_role:
        db.execute(user_roles.insert().values(user_id=user.id, role_id=student_role.id))

    student = Student(
        user_id=user.id,
        group_id=group.id,
        record_book=payload.record_book,
        course=payload.course,
        insert_year=payload.insert_year,
    )
    db.add(student); db.commit(); db.refresh(student)

    return {
        "id": student.id,
        "user_id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "group_id": group.id,
        "record_book": student.record_book,
        "course": student.course,
        "insert_year": student.insert_year,
    }

@router.post("/students/{student_id}/patch", dependencies=[Depends(require_permission("users:update"))])
def admin_update_student(student_id: int, payload: AdminStudentUpdate, db: Session = Depends(get_db)):
    s = db.get(Student, student_id)
    if not s:
        raise HTTPException(status_code=404, detail="Student not found")
    if payload.group_id is not None: s.group_id = payload.group_id
    if payload.record_book is not None: s.record_book = payload.record_book
    if payload.insert_year is not None: s.insert_year = payload.insert_year
    if payload.course is not None: s.course = payload.course
    db.commit(); db.refresh(s)
    return {
        "id": s.id, "user_id": s.user_id, "group_id": s.group_id,
        "record_book": s.record_book, "insert_year": s.insert_year, "course": s.course
    }

@router.post("/students/{student_id}/delete", dependencies=[Depends(require_permission("users:delete"))])
def admin_delete_student(student_id: int, db: Session = Depends(get_db)):
    s = db.get(Student, student_id)
    if not s:
        raise HTTPException(status_code=404, detail="Student not found")
    db.delete(s); db.commit()
    return {"ok": True}


@router.post("/groups", dependencies=[Depends(require_permission("schedules:create"))])
def admin_create_group(payload: GroupCreateIn, db: Session = Depends(get_db)):
    if db.scalar(select(Group.id).where(Group.identifier == payload.identifier)):
        raise HTTPException(status_code=400, detail="Group identifier already exists")
    g = Group(identifier=payload.identifier, code=payload.code, title=payload.title)
    db.add(g); db.commit()
    return {"id": g.id, "identifier": g.identifier, "code": g.code, "title": g.title}

@router.post("/groups/{group_id}/patch", dependencies=[Depends(require_permission("schedules:update"))])
def admin_update_group(group_id: int, payload: GroupCreateIn, db: Session = Depends(get_db)):
    g = db.get(Group, group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    duplicate = db.scalar(
        select(Group.id).where(
            Group.identifier == payload.identifier,
            Group.id != group_id,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=400, detail="Group identifier already exists")
    g.identifier = payload.identifier
    if payload.code is not None:
        g.code = payload.code
    if payload.title is not None:
        g.title = payload.title
    db.commit()
    db.refresh(g)
    return {"id": g.id, "identifier": g.identifier, "code": g.code, "title": g.title}

@router.post("/groups/{group_id}/delete", dependencies=[Depends(require_permission("schedules:delete"))])
def admin_delete_group(group_id: int, db: Session = Depends(get_db)):
    g = db.get(Group, group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    db.delete(g)
    db.commit()
    return {"ok": True}


@router.get("/groups", dependencies=[Depends(require_permission("schedules:read"))])
def admin_list_groups(db: Session = Depends(get_db), q: str | None = Query(None)):
    stmt = select(Group)
    if q:
        stmt = stmt.where(or_(
            Group.identifier.ilike(f"%{q}%"),
            Group.code.ilike(f"%{q}%"),
            Group.title.ilike(f"%{q}%"),
        ))
    rows = db.scalars(stmt).all()
    return [
        {"id": g.id, "identifier": g.identifier, "code": g.code, "title": g.title}
        for g in rows
    ]

@router.post("/teachers", dependencies=[Depends(require_permission("schedules:create"))])
def admin_create_teacher(payload: TeacherCreateIn, db: Session = Depends(get_db)):
    t = Teacher(
        user_id=payload.user_id, full_name=payload.full_name, email=payload.email,
        phone=payload.phone, subject=payload.subject, subdivision_id=payload.subdivision_id
    )
    db.add(t); db.flush()
    if payload.subject_codes is not None or payload.subject_ids:
        _replace_teacher_subjects(
            t, _subjects_from_references(db, payload.subject_codes, payload.subject_ids)
        )
    db.commit()
    return {
        "id": t.id,
        "full_name": t.full_name,
        "subject_identifiers": [s.identifier for s in t.subjects],
        "subject_codes": [s.code for s in t.subjects],
        "subject_ids": [s.id for s in t.subjects],
    }

@router.post("/teachers/{teacher_id}/delete", dependencies=[Depends(require_permission("users:delete"))])
def admin_delete_teacher(teacher_id: int, db: Session = Depends(get_db)):
    t = db.scalar(
        select(Teacher)
        .options(selectinload(Teacher.subjects).selectinload(Subject.teachers))
        .where(Teacher.id == teacher_id)
    )
    if not t:
        raise HTTPException(status_code=404, detail="Teacher not found")
    orphaned = [subject.code or str(subject.id) for subject in t.subjects if len(subject.teachers) == 1]
    if orphaned:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Teacher is the only teacher of a subject",
                "subjects": orphaned,
            },
        )
    for subject in t.subjects:
        if subject.primary_teacher_id == t.id:
            subject.primary_teacher = next(
                item for item in subject.teachers if item.id != t.id
            )
    try:
        db.delete(t)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Teacher is used by journal or other protected records",
        ) from exc
    return {"ok": True}


@router.post("/teachers/{teacher_id}/subjects", dependencies=[Depends(require_permission("schedules:update"))])
def admin_set_teacher_subjects(teacher_id: int, payload: TeacherSubjectsIn, db: Session = Depends(get_db)):
    t = db.get(Teacher, teacher_id)
    if not t:
        raise HTTPException(status_code=404, detail="Teacher not found")
    _replace_teacher_subjects(
        t, _subjects_from_references(db, payload.subject_codes, payload.subject_ids)
    )
    db.commit()
    return {
        "teacher_id": t.id,
        "subject_identifiers": [s.identifier for s in t.subjects],
        "subject_codes": [s.code for s in t.subjects],
        "subject_ids": [s.id for s in t.subjects],
    }

@router.post("/teachers/{teacher_id}/patch", dependencies=[Depends(require_permission("users:update"))])
def admin_update_teacher(teacher_id: int, payload: AdminTeacherUpdate, db: Session = Depends(get_db)):
    t = db.get(Teacher, teacher_id)
    if not t:
        raise HTTPException(status_code=404, detail="Teacher not found")

    if payload.full_name is not None: t.full_name = payload.full_name
    if payload.email is not None: t.email = payload.email
    if payload.phone is not None: t.phone = payload.phone
    if payload.subject is not None: t.subject = payload.subject
    if payload.subdivision_id is not None: t.subdivision_id = payload.subdivision_id
    if payload.subject_codes is not None or payload.subject_ids is not None:
        _replace_teacher_subjects(
            t, _subjects_from_references(db, payload.subject_codes, payload.subject_ids)
        )

    db.commit(); db.refresh(t)
    return {
        "id": t.id,
        "full_name": t.full_name,
        "email": t.email,
        "phone": t.phone,
        "subject": t.subject,
        "subdivision_id": t.subdivision_id,
        "subject_ids": [s.id for s in t.subjects],
        "subject_identifiers": [s.identifier for s in t.subjects],
        "subject_codes": [s.code for s in t.subjects],
    }

@router.get("/teachers", dependencies=[Depends(require_permission("schedules:read"))])
def admin_list_teachers(db: Session = Depends(get_db), q: str | None = Query(None), subdivision_id: int | None = Query(None)):
    qstmt = select(Teacher)
    if q:
        qstmt = qstmt.where(or_(Teacher.full_name.ilike(f"%{q}%"), Teacher.email.ilike(f"%{q}%")))
    if subdivision_id:
        qstmt = qstmt.where(Teacher.subdivision_id == subdivision_id)
    rows = db.scalars(qstmt).all()
    ids = [t.id for t in rows]
    subj_rows = db.execute(
        select(
            teacher_subjects.c.teacher_id,
            Subject.id,
            Subject.identifier,
            Subject.title,
            Subject.code,
        )
        .join(Subject, Subject.id == teacher_subjects.c.subject_id)
        .where(teacher_subjects.c.teacher_id.in_(ids))
    ).all()
    subj_map: dict[int, list[dict]] = {i: [] for i in ids}
    for tid, sid, identifier, stitle, scode in subj_rows:
        subj_map.setdefault(tid, []).append(
            {
                "id": sid,
                "identifier": identifier,
                "title": stitle,
                "code": scode,
                "subject_code": scode,
            }
        )

    return [
        {
            "id": t.id, "full_name": t.full_name, "email": t.email, "phone": t.phone,
            "subject": t.subject, "subdivision_id": t.subdivision_id,
            "subjects": subj_map.get(t.id, [])
        } for t in rows
    ]

@router.post("/lessons/{lesson_id}/patch", dependencies=[Depends(require_permission("schedules:update"))])
def admin_update_lesson(lesson_id: int, payload: LessonUpdate, db: Session = Depends(get_db)):
    l = db.get(Lesson, lesson_id)
    if not l:
        raise HTTPException(status_code=404, detail="Lesson not found")

    if payload.group_code is not None:
        g = db.scalar(select(Group).where(Group.code == payload.group_code))
        if not g:
            raise HTTPException(status_code=404, detail="Group not found")
        l.group_id = g.id

    if payload.room_code is not None:
        r = db.scalar(select(Room).where(Room.code == payload.room_code))
        if not r:
            raise HTTPException(status_code=404, detail="Room not found")
        l.room_id = r.id

    if (
        payload.subject_identifier is not None
        or payload.subject_code is not None
        or payload.subject_id is not None
    ):
        l.subject_id = resolve_subject(
            db,
            payload.subject_code,
            payload.subject_id,
            subject_identifier=payload.subject_identifier,
        ).id
    elif payload.subject_title is not None:
        matches = db.scalars(
            select(Subject)
            .where(Subject.title == payload.subject_title)
            .order_by(Subject.id)
            .limit(2)
        ).all()
        if not matches:
            raise HTTPException(status_code=404, detail="Subject not found")
        if len(matches) > 1:
            raise HTTPException(
                status_code=409,
                detail="Subject title is ambiguous; use subject_id or subject_identifier",
            )
        l.subject_id = matches[0].id

    if payload.teacher_id is not None:
        l.teacher_id = payload.teacher_id
    elif payload.teacher_email is not None:
        t = db.scalar(select(Teacher).where(Teacher.email == payload.teacher_email))
        if not t:
            raise HTTPException(status_code=404, detail="Teacher not found")
        l.teacher_id = t.id
    elif payload.teacher_full_name is not None:
        t = db.scalar(select(Teacher).where(Teacher.full_name == payload.teacher_full_name))
        if not t:
            raise HTTPException(status_code=404, detail="Teacher not found")
        l.teacher_id = t.id

    if payload.lesson_number is not None:
        l.lesson_number = payload.lesson_number
    if payload.starts_at is not None:
        l.starts_at = payload.starts_at
    if payload.ends_at is not None:
        l.ends_at = payload.ends_at
    if payload.subject_type is not None:
        l.subject_type = payload.subject_type
    if "topic" in payload.model_fields_set:
        l.topic = payload.topic
    if payload.notes is not None:
        l.notes = payload.notes

    if l.teacher_id is not None and l.subject_id is not None:
        ensure_teacher_linked_to_subject(db, l.teacher_id, l.subject_id)

    db.commit()
    db.refresh(l)

    return {
        "id": l.id,
        "group_id": l.group_id,
        "subject_id": l.subject_id,
        "subject_identifier": l.subject.identifier if l.subject else None,
        "subject_code": l.subject.code if l.subject else None,
        "teacher_id": l.teacher_id,
        "room_id": l.room_id,
        "lesson_number": l.lesson_number,
        "starts_at": l.starts_at,
        "ends_at": l.ends_at,
        "subject_type": l.subject_type,
        "topic": l.topic,
        "notes": l.notes,
    }

@router.post("/lessons/{lesson_id}/delete", dependencies=[Depends(require_permission("schedules:delete"))])
def admin_delete_lesson(lesson_id: int, db: Session = Depends(get_db)):
    l = db.get(Lesson, lesson_id)
    if not l:
        raise HTTPException(status_code=404, detail="Lesson not found")
    db.delete(l)
    db.commit()
    return {"ok": True}

@router.post("/rooms", dependencies=[Depends(require_permission("schedules:create"))])
def admin_create_room(payload: RoomCreateIn, db: Session = Depends(get_db)):
    if db.scalar(select(Room).where(Room.code == payload.code)):
        raise HTTPException(status_code=400, detail="Room already exists")
    r = Room(code=payload.code, title=payload.title, capacity=payload.capacity)
    db.add(r); db.commit()
    return {"id": r.id, "code": r.code}

@router.post("/rooms/{room_id}/patch", dependencies=[Depends(require_permission("schedules:update"))])
def admin_update_room(room_id: int, payload: RoomCreateIn, db: Session = Depends(get_db)):
    r = db.get(Room, room_id)
    if not r:
        raise HTTPException(status_code=404, detail="Room not found")
    if payload.code is not None:
        r.code = payload.code
    if payload.title is not None:
        r.title = payload.title
    if payload.capacity is not None:
        r.capacity = payload.capacity
    db.commit()
    db.refresh(r)
    return {"id": r.id, "code": r.code, "title": r.title, "capacity": r.capacity}

@router.post("/rooms/{room_id}/delete", dependencies=[Depends(require_permission("schedules:delete"))])
def admin_delete_room(room_id: int, db: Session = Depends(get_db)):
    r = db.get(Room, room_id)
    if not r:
        raise HTTPException(status_code=404, detail="Room not found")
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.get("/rooms", dependencies=[Depends(require_permission("schedules:read"))])
def admin_list_rooms(db: Session = Depends(get_db), q: str | None = Query(None)):
    stmt = select(Room)
    if q:
        stmt = stmt.where(or_(Room.code.ilike(f"%{q}%"), Room.title.ilike(f"%{q}%")))
    rows = db.scalars(stmt).all()
    return [{"id": r.id, "code": r.code, "title": r.title, "capacity": r.capacity} for r in rows]

@router.post("/subjects", dependencies=[Depends(require_permission("schedules:create"))])
def admin_create_subject(payload: SubjectCreateIn, db: Session = Depends(get_db)):
    if payload.identifier and db.scalar(
        select(Subject.id).where(Subject.identifier == payload.identifier)
    ):
        raise HTTPException(status_code=400, detail="Subject identifier already exists")
    teachers = resolve_subject_teachers(db, payload.teacher_ids)
    s = Subject(
        title=payload.title,
        code=payload.subject_code,
        primary_teacher_id=teachers[0].id,
        grade_type=payload.grade_type,
    )
    if payload.identifier:
        s.identifier = payload.identifier
    try:
        db.add(s)
        db.flush()
        s.teachers = teachers
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Subject already exists") from exc
    db.refresh(s)
    return _subject_out(s)

@router.post("/subjects/{subject_identifier}/patch", dependencies=[Depends(require_permission("schedules:update"))])
def admin_update_subject(subject_identifier: str, payload: SubjectCreateIn, db: Session = Depends(get_db)):
    s = _subject_from_path(db, subject_identifier)

    if payload.identifier and db.scalar(
        select(Subject.id).where(
            Subject.identifier == payload.identifier,
            Subject.id != s.id,
        )
    ):
        raise HTTPException(status_code=400, detail="Subject identifier already exists")

    if payload.identifier is not None:
        s.identifier = payload.identifier
    if payload.title is not None:
        s.title = payload.title
    if payload.subject_code is not None:
        s.code = payload.subject_code
    if payload.grade_type is not None:
        s.grade_type = payload.grade_type
    _set_subject_teachers(db, s, payload.teacher_ids)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Subject already exists") from exc
    db.refresh(s)
    return _subject_out(s)

@router.post("/subjects/{subject_identifier}/delete", dependencies=[Depends(require_permission("schedules:delete"))])
def admin_delete_subject(subject_identifier: str, db: Session = Depends(get_db)):
    s = _subject_from_path(db, subject_identifier)
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.get("/subjects", dependencies=[Depends(require_permission("schedules:read"))])
def admin_list_subjects(db: Session = Depends(get_db), q: str | None = Query(None)):
    try:
        stmt = select(Subject).options(
            selectinload(Subject.teachers), selectinload(Subject.primary_teacher)
        )
        if q:
            stmt = stmt.where(
                or_(
                    Subject.identifier.ilike(f"%{q}%"),
                    Subject.title.ilike(f"%{q}%"),
                    Subject.code.ilike(f"%{q}%")
                )
            )

        stmt = stmt.order_by(Subject.id.asc())

        rows = db.scalars(stmt).all()
        return [_subject_out(s) for s in rows]
    except (OperationalError, ProgrammingError):
        db.rollback()
        # Compatibility fallback while a client database is waiting for the migration.
        stmt = """
            SELECT s.id, s.title, s.code, s.primary_teacher_id, t.full_name AS primary_teacher_name
            FROM subjects s
            LEFT JOIN teachers t ON t.id = s.primary_teacher_id
        """
        params: dict[str, str] = {}
        if q:
            stmt += " WHERE s.title ILIKE :pattern OR s.code ILIKE :pattern"
            params["pattern"] = f"%{q}%"
        stmt += " ORDER BY s.id ASC"

        rows = db.execute(text(stmt), params).mappings().all()
        return [
            {
                "id": row["id"],
                "identifier": None,
                "title": row["title"],
                "code": row["code"],
                "subject_code": row["code"],
                "grade_type": None,
                "primary_teacher_id": row["primary_teacher_id"],
                "primary_teacher_name": row["primary_teacher_name"],
                "teacher_ids": (
                    [row["primary_teacher_id"]] if row["primary_teacher_id"] else []
                ),
                "teachers": (
                    [{
                        "id": row["primary_teacher_id"],
                        "full_name": row["primary_teacher_name"],
                    }]
                    if row["primary_teacher_id"] else []
                ),
            }
            for row in rows
        ]


@router.get("/subject_types", response_model=list[SubjectTypeOut])
def list_subject_types(db: Session = Depends(get_db)):
    return db.scalars(select(SubjectType)).all()

@router.post("/subject_types", response_model=SubjectTypeOut, dependencies=[Depends(require_role_any(["administrator", "director"]))])
def create_subject_type(data: SubjectTypeCreate, db: Session = Depends(get_db)):
    if db.scalar(select(SubjectType).where(SubjectType.name == data.name)):
        raise HTTPException(status_code=400, detail="Такой тип дисциплины уже существует")
    t = SubjectType(name=data.name)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t

@router.post("/subject_types/{type_id}/patch", response_model=SubjectTypeOut, dependencies=[Depends(require_role_any(["administrator", "director"]))])
def update_subject_type(type_id: int, data: SubjectTypeUpdate, db: Session = Depends(get_db)):
    t = db.get(SubjectType, type_id)
    if not t:
        raise HTTPException(status_code=404, detail="Тип дисциплины не найден")
    if data.name:
        existing = db.scalar(select(SubjectType).where(SubjectType.name == data.name, SubjectType.id != type_id))
        if existing:
            raise HTTPException(status_code=400, detail="Тип с таким названием уже существует")
        t.name = data.name
    db.commit()
    db.refresh(t)
    return t

@router.post("/subject_types/{type_id}/delete", dependencies=[Depends(require_role_any(["administrator", "director"]))])
def delete_subject_type(type_id: int, db: Session = Depends(get_db)):
    t = db.get(SubjectType, type_id)
    if not t:
        raise HTTPException(status_code=404, detail="Тип дисциплины не найден")
    db.delete(t)
    db.commit()
    return {"ok": True}

@router.post("/subdivisions", dependencies=[Depends(require_permission("schedules:create"))])
def admin_create_subdivision(payload: SubdivisionCreateIn, db: Session = Depends(get_db)):
    sd = Subdivision(name=payload.name, type=payload.type, code=payload.code, parent_id=payload.parent_id)
    db.add(sd); db.commit()
    return {"id": sd.id, "name": sd.name, "type": sd.type, "code": sd.code, "parent_id": sd.parent_id}

@router.get("/subdivisions", dependencies=[Depends(require_permission("schedules:read"))])
def admin_list_subdivisions(
    db: Session = Depends(get_db),
    q: str | None = Query(None),
    type: str | None = Query(None),
    parent_id: int | None = Query(None)
):
    stmt = select(Subdivision)
    if q:
        stmt = stmt.where(Subdivision.name.ilike(f"%{q}%"))
    if type:
        stmt = stmt.where(Subdivision.type == type)
    if parent_id is not None:
        stmt = stmt.where(Subdivision.parent_id == parent_id)
    rows = db.scalars(stmt).all()
    return [
        {"id": s.id, "name": s.name, "type": s.type, "code": s.code, "parent_id": s.parent_id}
        for s in rows
    ]

@router.post("/subdivisions/{subdivision_id}/assign-teachers", dependencies=[Depends(require_permission("schedules:update"))])
def admin_subdivision_assign_teachers(subdivision_id: int, payload: SubdivisionAssignTeachersIn, db: Session = Depends(get_db)):
    if not db.get(Subdivision, subdivision_id):
        raise HTTPException(status_code=404, detail="Subdivision not found")
    updated = 0
    for tid in payload.teacher_ids:
        t = db.get(Teacher, tid)
        if not t:
            continue
        t.subdivision_id = subdivision_id
        updated += 1
    db.commit()
    return {"subdivision_id": subdivision_id, "assigned": updated}

@router.get("/subdivisions/{subdivision_id}/teachers", dependencies=[Depends(require_permission("schedules:read"))])
def admin_subdivision_teachers(subdivision_id: int, db: Session = Depends(get_db)):
    if not db.get(Subdivision, subdivision_id):
        raise HTTPException(status_code=404, detail="Subdivision not found")
    rows = db.scalars(select(Teacher).where(Teacher.subdivision_id == subdivision_id)).all()
    return [
        {"id": t.id, "full_name": t.full_name, "email": t.email, "phone": t.phone, "subject": t.subject}
        for t in rows
    ]
