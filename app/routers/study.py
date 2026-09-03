from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
from datetime import datetime
from app.core.deps import get_db, get_current_user, require_permission
from app.models.grade import Student as StudentModel, Grade
from app.models.schedule import Group, Subject, Lesson, Teacher
from app.schemas.user import MeOut
from app.models.user import User
from app.services.subject_teacher_service import subject_teacher_payload

router = APIRouter(prefix="/students", tags=["study"])

@router.get("/{student_id}/study/overview")
def student_study_overview(
    student_id: int,
    db: Session = Depends(get_db),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    me=Depends(get_current_user),
    _ = Depends(require_permission("schedules:read")),
):
    st = db.get(StudentModel, student_id)
    if not st:
        raise HTTPException(status_code=404, detail="Student not found")

    group = db.get(Group, st.group_id)
    if not group:
        return {"subjects": [], "lessons": [], "grades": []}

    subj_q = (
        select(Subject)
        .options(
            selectinload(Subject.primary_teacher),
            selectinload(Subject.teachers),
        )
        .join(Lesson, Lesson.subject_id == Subject.id)
        .where(Lesson.group_id == group.id)
    )
    if date_from:
        subj_q = subj_q.where(Lesson.starts_at >= date_from)
    if date_to:
        subj_q = subj_q.where(Lesson.starts_at < date_to)
    subjects = db.scalars(subj_q.distinct()).all()

    subj_ids = [s.id for s in subjects] or [-1]

    les_q = (
        select(Lesson)
        .where(Lesson.group_id == group.id, Lesson.subject_id.in_(subj_ids))
        .options(
            selectinload(Lesson.subject),
            selectinload(Lesson.teacher),
            selectinload(Lesson.room),
        )
        .order_by(Lesson.starts_at)
    )
    if date_from:
        les_q = les_q.where(Lesson.starts_at >= date_from)
    if date_to:
        les_q = les_q.where(Lesson.starts_at < date_to)
    lessons = db.scalars(les_q).all()

    gr_q = select(Grade).where(Grade.student_id == student_id)
    if subj_ids:
        gr_q = gr_q.where(Grade.subject_id.in_(subj_ids))
    grades = db.scalars(gr_q.order_by(Grade.graded_at.desc())).all()

    subj_dict = {}
    for s in subjects:
        subj_dict[s.id] = {
            "id": s.id,
            "title": s.title,
            "code": s.code,
            "subject_code": s.code,
            "primary_teacher_id": s.primary_teacher_id,
            "primary_teacher_name": s.primary_teacher.full_name if s.primary_teacher else None,
            **subject_teacher_payload(s),
            "grade_type": s.grade_type,
            "grades": [],
            "final_grade": None,
        }

    for g in grades:
        if g.subject_id in subj_dict:
            subj_data = subj_dict[g.subject_id]
            grade_entry = {
                "id": g.id,
                "type": g.grade_type,
                "value": g.value,
                "graded_at": g.graded_at,
                "lesson_id": g.lesson_id,
                "lesson_date": (g.lesson.starts_at if g.lesson else None),
                "teacher_id": g.teacher_id,
                "comment": g.comment,
            }
            subj_data["grades"].append(grade_entry)

            if g.grade_type.lower() in ["итог", "final", "exam", "зачет"]:
                subj_data["final_grade"] = g.value

    return {
        "student_id": st.id,
        "student_name": st.user.full_name,
        "group": group.code,
        "subjects": list(subj_dict.values()),
        "lessons": [
            {
                "id": l.id,
                "subject_id": l.subject_id,
                "subject_code": l.subject.code if l.subject else None,
                "subject_title": l.subject.title if l.subject else None,
                "subject_type": l.subject_type,
                "teacher": l.teacher.full_name if l.teacher else None,
                "room": l.room.code if l.room else None,
                "starts_at": l.starts_at,
                "ends_at": l.ends_at,
            }
            for l in lessons
        ],
    }

@router.get("/study/overview/all")
def all_students_study_overview(
    db: Session = Depends(get_db),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    me=Depends(get_current_user),
    _ = Depends(require_permission("schedules:read")),
):
    students = db.query(StudentModel).join(User, User.id == StudentModel.user_id).all()
    result = []

    for st in students:
        group = db.get(Group, st.group_id)
        if not group:
            continue

        subj_q = select(Subject).options(
            selectinload(Subject.primary_teacher), selectinload(Subject.teachers)
        ) \
            .join(Lesson, Lesson.subject_id == Subject.id) \
            .where(Lesson.group_id == group.id)
        if date_from:
            subj_q = subj_q.where(Lesson.starts_at >= date_from)
        if date_to:
            subj_q = subj_q.where(Lesson.starts_at < date_to)
        subjects = db.scalars(subj_q.distinct()).all()

        subj_ids = [s.id for s in subjects] or [-1]

        les_q = select(Lesson).where(Lesson.group_id == group.id, Lesson.subject_id.in_(subj_ids))
        if date_from:
            les_q = les_q.where(Lesson.starts_at >= date_from)
        if date_to:
            les_q = les_q.where(Lesson.starts_at < date_to)
        lessons = db.scalars(les_q.order_by(Lesson.starts_at)).all()

        gr_q = select(Grade).where(Grade.student_id == st.id)
        if subj_ids:
            gr_q = gr_q.where(Grade.subject_id.in_(subj_ids))
        grades = db.scalars(gr_q.order_by(Grade.graded_at.desc())).all()

        subj_dict = {}
        for s in subjects:
            subj_dict[s.id] = {
                "id": s.id,
                "title": s.title,
                "code": s.code,
                "subject_code": s.code,
                "primary_teacher_id": s.primary_teacher_id,
                "primary_teacher_name": s.primary_teacher.full_name if s.primary_teacher else None,
                **subject_teacher_payload(s),
                "grade_type": s.grade_type,
                "grades": [],
                "final_grade": None, 
            }

        for g in grades:
            if g.subject_id in subj_dict:
                subj_data = subj_dict[g.subject_id]
                grade_entry = {
                    "id": g.id,
                    "type": g.grade_type,
                    "value": g.value,
                    "graded_at": g.graded_at,
                    "lesson_id": g.lesson_id,
                    "lesson_date": (g.lesson.starts_at if g.lesson else None),
                    "teacher_id": g.teacher_id,
                    "comment": g.comment,
                }
                subj_data["grades"].append(grade_entry)

                if g.grade_type.lower() in ["итог", "final", "exam", "зачет"]:
                    subj_data["final_grade"] = g.value

        result.append({
            "student_id": st.id,
            "student_name": st.user.full_name,
            "group": group.code if group else None,
            "subjects": list(subj_dict.values()),
            "lessons": [
                {
                    "id": l.id,
                    "subject_id": l.subject_id,
                    "subject_code": l.subject.code if l.subject else None,
                    "teacher": l.teacher.full_name if l.teacher else None,
                    "room": l.room.code if l.room else None,
                    "starts_at": l.starts_at,
                    "ends_at": l.ends_at,
                    "subject_type": l.subject_type,
                } for l in lessons
            ]
        })

    return result
