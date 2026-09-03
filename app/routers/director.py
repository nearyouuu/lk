from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, select
from app.core.deps import get_db, require_role_any
from app.models.user import User
from app.models.schedule import Group, Teacher, Subdivision, Subject
from app.models.grade import Student, Grade


router = APIRouter(
    prefix="/director",
    tags=["director"],
    dependencies=[Depends(require_role_any(["director"]))],
)

@router.get("/groups")
def list_groups(db: Session = Depends(get_db), q: str | None = Query(None)):
    stmt = select(Group)
    if q:
        stmt = stmt.where(or_(
            Group.identifier.ilike(f"%{q}%"),
            Group.code.ilike(f"%{q}%"),
            Group.title.ilike(f"%{q}%"),
        ))
    groups = db.scalars(stmt).all()
    return [
        {"id": g.id, "identifier": g.identifier, "code": g.code, "title": g.title}
        for g in groups
    ]

@router.get("/teachers")
def list_teachers(db: Session = Depends(get_db), q: str | None = Query(None), subdivision_id: int | None = Query(None)):
    stmt = select(Teacher)
    if q:
        stmt = stmt.where(Teacher.full_name.ilike(f"%{q}%") | Teacher.email.ilike(f"%{q}%"))
    if subdivision_id:
        stmt = stmt.where(Teacher.subdivision_id == subdivision_id)
    teachers = db.scalars(stmt).all()
    return [
        {"id": t.id, "full_name": t.full_name, "email": t.email, "phone": t.phone, "subject": t.subject}
        for t in teachers
    ]

@router.get("/subdivisions")
def list_subdivisions(db: Session = Depends(get_db), q: str | None = Query(None), type: str | None = Query(None)):
    stmt = select(Subdivision)
    if q:
        stmt = stmt.where(Subdivision.name.ilike(f"%{q}%"))
    if type:
        stmt = stmt.where(Subdivision.type == type)
    subdivisions = db.scalars(stmt).all()
    return [
        {"id": s.id, "name": s.name, "type": s.type, "code": s.code, "parent_id": s.parent_id}
        for s in subdivisions
    ]

@router.get("/groups/{group_id}/students")
def list_group_students(group_id: int, db: Session = Depends(get_db)):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    students = (
        db.query(Student)
        .join(User, User.id == Student.user_id)
        .filter(Student.group_id == group_id)
        .all()
    )

    return {
        "group": {"id": group.id, "code": group.code, "title": group.title},
        "students": [
            {
                "id": s.user.id,
                "full_name": s.user.full_name,
                "email": s.user.email,
                "phone": s.user.phone,
                "record_book": s.record_book,
                "course": s.course,
                "insert_year": s.insert_year,
                "student_id": s.id,
            }
            for s in students
        ]
    }

@router.get("/students/{student_id}/grades")
def student_grades(student_id: int, db: Session = Depends(get_db)):
    st = db.get(Student, student_id)
    if not st:
        raise HTTPException(status_code=404, detail="Student not found")

    grades = db.query(Grade).filter(Grade.student_id == student_id).all()
    return [
        {
            "id": g.id,
            "subject_id": g.subject_id,
            "subject_code": g.subject.code if g.subject else None,
            "teacher_id": g.teacher_id,
            "lesson_id": g.lesson_id,
            "grade_type": g.grade_type,
            "value": g.value,
            "graded_at": g.graded_at,
            "comment": g.comment,
        }
        for g in grades
    ]
