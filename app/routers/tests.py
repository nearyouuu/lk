from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Body, Form
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, delete, func
from datetime import datetime, timedelta
import json
import pandas as pd
import io
import random
from app.core.deps import get_db, get_current_user, require_role_any, is_admin, require_feature
from app.models.user import User
from app.models.grade import Student as StudentModel
from app.models.schedule import Group, Teacher
from app.models.testing import (
    Test, Question, TestGroupAccess, TestAttempt,
    QuestionType, AttemptStatus
)
from app.schemas.testing import (
    TestCreate, TestUpdate, AssignGroupsIn,
    TestOut, TestAdminOut,
    QuestionOut, QuestionAdminOut,
    StartOut, SubmitIn,
    AttemptOut, AttemptDetailOut, ReviewIn,
    TestShortOut, QuestionUpdate, TestImportCreate
)
from app.services.testing_service import (
    can_start_attempt, make_attempt_token, verify_attempt_token,
    calc_must_finish_at, evaluate_auto,get_max_score_for_test,
    get_points_per_question, evaluate_auto_detailed
)
from sqlalchemy.sql.expression import func as sa_func


router = APIRouter(
    prefix="/tests",
    tags=["tests"],
    dependencies=[Depends(require_feature("tests"))],
)


def _ensure_teacher_or_admin(user: User, db: Session):
    if is_admin(user, db):
        return
    t = db.scalar(select(Teacher).where(Teacher.user_id == user.id))
    if not t:
        raise HTTPException(status_code=403, detail="Только преподаватель или админ")

def _student(db: Session, user: User) -> StudentModel:
    st = db.scalar(select(StudentModel).where(StudentModel.user_id == user.id))
    if not st:
        raise HTTPException(status_code=403, detail="Только для студентов")
    return st

def _normalize_match_for_save(options: dict | None) -> dict | None:
    """Преобразует формат {left: [...], right: [...]} -> {лево: право}"""
    if not options or not isinstance(options, dict):
        return options
    if "left" in options and "right" in options:
        left = options.get("left", [])
        right = options.get("right", [])
        return {l: (right[i] if i < len(right) else None) for i, l in enumerate(left)}
    return options

def _normalize_match_for_read(options: dict | None, correct_answers: dict | None = None) -> dict | None:
    """Преобразует формат {лево: право} -> {left: [...], right: [...]}"""
    if not options or not isinstance(options, dict):
        return options
    left = list(options.keys())
    right = []
    if isinstance(correct_answers, str):
        try:
            correct_answers = json.loads(correct_answers)
        except Exception:
            correct_answers = None
    if isinstance(correct_answers, dict):
        right = [correct_answers.get(k) for k in left if correct_answers.get(k)]
    return {"left": left, "right": right}

@router.post("", response_model=TestOut, dependencies=[Depends(require_role_any(["administrator", "teacher"]))])
@router.post("/", response_model=TestOut, dependencies=[Depends(require_role_any(["administrator", "teacher"]))], include_in_schema=False)
def create_test(payload: TestCreate, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _ensure_teacher_or_admin(me, db)

    test = Test(
        title=payload.title,
        description=payload.description,
        duration_minutes=payload.duration_minutes,
        max_attempts=payload.max_attempts,
        deadline=payload.deadline,
        created_by_id=me.id,
        teacher_id=payload.teacher_id
    )
    db.add(test)
    db.flush()

    for gid in (payload.group_ids or []):
        db.add(TestGroupAccess(test_id=test.id, group_id=gid))

    for i, q in enumerate(payload.questions):
        if q.points <=0:
            raise HTTPException(status_code=400, detail="Баллы не могут быть отрицательными")
        options = _normalize_match_for_save(q.options) if q.type == QuestionType.match else q.options
        db.add(Question(
            test_id=test.id,
            type=q.type,
            text=q.text,
            options=options,
            correct_answers=q.correct_answers,
            points=q.points,
            order_index=q.order_index if q.order_index is not None else i
        ))

    db.commit()
    db.expire_all()
    db.refresh(test)
    return get_test(test.id, db, me)

@router.get(
    "",
    response_model=list[TestOut],
    dependencies=[Depends(require_role_any(["administrator", "teacher", "student"]))],
)
@router.get(
    "/",
    response_model=list[TestOut],
    dependencies=[Depends(require_role_any(["administrator", "teacher", "student"]))],
    include_in_schema=False,
)
def list_tests(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
    group_code: str | None = Query(None, description="Код группы, например 'ИСб-22'")
):
    group_ids = []
    teacher = None
    is_admin_user = is_admin(me, db)

    if not is_admin_user:
        teacher = db.scalar(select(Teacher).where(Teacher.user_id == me.id))
        if not teacher:
            st = _student(db, me)
            group_ids = [st.group_id]

    q = select(Test).options(joinedload(Test.questions), joinedload(Test.groups))
    if group_code:
        group = db.scalar(select(Group).where(Group.code == group_code))
        if not group:
            raise HTTPException(status_code=404, detail=f"Группа '{group_code}' не найдена")
        q = q.where(
            Test.id.in_(
                select(TestGroupAccess.test_id).where(TestGroupAccess.group_id == group.id)
            )
        )
    elif group_ids:
        q = q.where(
            Test.id.in_(
                select(TestGroupAccess.test_id).where(TestGroupAccess.group_id.in_(group_ids))
            )
        )

    tests = db.scalars(q.order_by(Test.created_at.desc())).unique().all()

    attempt_stats: dict[int, dict] = {}

    summary_rows = db.execute(
        select(
            TestAttempt.test_id,
            func.count(TestAttempt.id).label("total_attempts"),
            func.count(func.distinct(TestAttempt.student_id)).label("unique_students"),
            func.max(TestAttempt.started_at).label("last_attempt"),
        )
        .group_by(TestAttempt.test_id)
    ).all()

    for row in summary_rows:
        attempt_stats[row.test_id] = {
            "total_attempts": row.total_attempts,
            "unique_students": row.unique_students,
            "last_attempt": row.last_attempt,
            "students": []
        }

    detail_rows = db.execute(
        select(
            TestAttempt.test_id,
            TestAttempt.student_id,
            func.count(TestAttempt.id).label("attempts_count"),
            func.max(TestAttempt.started_at).label("last_attempt"),
            func.max(TestAttempt.status).label("last_status"),
            func.coalesce(
                func.max(TestAttempt.teacher_score),
                func.max(TestAttempt.auto_score)
            ).label("last_score"),
        )
        .group_by(TestAttempt.test_id, TestAttempt.student_id)
    ).all()

    for row in detail_rows:
        if row.test_id not in attempt_stats:
            attempt_stats[row.test_id] = {
                "total_attempts": 0,
                "unique_students": 0,
                "last_attempt": None,
                "students": []
            }
        attempt_stats[row.test_id]["students"].append({
            "student_id": row.student_id,
            "attempts_count": row.attempts_count,
            "last_attempt": row.last_attempt,
            "last_status": row.last_status,
            "last_score": row.last_score,
        })

    result = []
    for t in tests:
        stats = attempt_stats.get(
            t.id,
            {"total_attempts": 0, "unique_students": 0, "last_attempt": None, "students": []}
        )
        result.append({
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "duration_minutes": t.duration_minutes,
            "max_attempts": t.max_attempts,
            "deadline": t.deadline,
            "is_active": t.is_active,
            "teacher_id": t.teacher_id,
            "questions": [
                QuestionOut(
                    id=q.id,
                    type=q.type,
                    text=q.text,
                    options=_normalize_match_for_read(q.options, q.correct_answers)
                    if q.type == QuestionType.match else q.options,
                    points=q.points,
                    order_index=q.order_index,
                )
                for q in sorted(t.questions, key=lambda z: z.order_index)
            ],
            "group_ids": [g.group_id for g in t.groups],
            "attempts_summary": stats
        })

    return result


@router.get("/my", response_model=list[TestOut], dependencies=[Depends(require_role_any(["teacher", "administrator"]))])
def list_my_tests(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _ensure_teacher_or_admin(me, db)
    teacher = db.scalar(select(Teacher).where(Teacher.user_id == me.id))
    q = select(Test).options(joinedload(Test.questions), joinedload(Test.groups))
    if teacher:
        q = q.where(Test.teacher_id == teacher.id)
    tests = db.scalars(q.order_by(Test.created_at.desc())).unique().all()

    return [
        TestOut(
            id=t.id,
            title=t.title,
            description=t.description,
            duration_minutes=t.duration_minutes,
            max_attempts=t.max_attempts,
            deadline=t.deadline,
            is_active=t.is_active,
            teacher_id=t.teacher_id,
            questions=[
                QuestionOut(
                    id=qq.id,
                    type=qq.type,
                    text=qq.text,
                    options=_normalize_match_for_read(qq.options, qq.correct_answers) if qq.type == QuestionType.match else qq.options,
                    points=qq.points,
                    order_index=qq.order_index
                )
                for qq in sorted(t.questions, key=lambda z: z.order_index)
            ],
            group_ids=[g.group_id for g in t.groups]
        )
        for t in tests
    ]


@router.get("/{test_id}", response_model=TestOut)
def get_test(test_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    t = db.scalar(
        select(Test)
        .options(joinedload(Test.questions))
        .where(Test.id == test_id)
    )
    if not t:
        raise HTTPException(status_code=404, detail="Test not found")

    teacher = db.scalar(select(Teacher).where(Teacher.user_id == me.id))
    admin = is_admin(me, db)
    is_teacher_or_admin = admin or bool(teacher)
    question_schema = QuestionAdminOut if is_teacher_or_admin else QuestionOut

    questions = []
    for q in sorted(t.questions, key=lambda z: z.order_index):
        if q.type == QuestionType.match:
            opts = _normalize_match_for_read(q.options, q.correct_answers)
        else:
            opts = q.options

        base = dict(
            id=q.id,
            type=q.type,
            text=q.text,
            options=opts,
            points=q.points,
            order_index=q.order_index,
        )
        if is_teacher_or_admin:
            base["correct_answers"] = q.correct_answers
        questions.append(question_schema(**base))

    total_points = get_max_score_for_test(t)
    points_per_question = get_points_per_question(t)

    schema = TestAdminOut if is_teacher_or_admin else TestOut
    data = schema(
        id=t.id,
        title=t.title,
        description=t.description,
        duration_minutes=t.duration_minutes,
        max_attempts=t.max_attempts,
        deadline=t.deadline,
        is_active=t.is_active,
        teacher_id=t.teacher_id,
        questions=questions,
        group_ids=[g.group_id for g in t.groups],
    )

    result = data.model_dump()
    result["total_points"] = total_points
    result["points_per_question"] = points_per_question
    return result


@router.post("/{test_id}/patch", response_model=TestOut, dependencies=[Depends(require_role_any(["administrator", "teacher"]))])
def update_test(test_id: int, payload: TestUpdate, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _ensure_teacher_or_admin(me, db)
    test = db.get(Test, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")

    for k, v in payload.model_dump(exclude_unset=True, exclude={"questions"}).items():
        setattr(test, k, v)

    if payload.questions is not None:
        existing = {q.id: q for q in test.questions}
        sent_ids = set()
        for i, qd in enumerate(payload.questions):
            options = _normalize_match_for_save(qd.options) if qd.type == QuestionType.match else qd.options
            if qd.id and qd.id in existing:
                q = existing[qd.id]
                for key, val in qd.model_dump(exclude_unset=True).items():
                    if key == "options":
                        setattr(q, key, options)
                    else:
                        setattr(q, key, val)
                sent_ids.add(q.id)
            else:
                nq = Question(
                    test_id=test.id,
                    type=qd.type or QuestionType.choice,
                    text=qd.text or "",
                    options=options,
                    correct_answers=qd.correct_answers,
                    points=qd.points or 1,
                    order_index=qd.order_index if qd.order_index is not None else i,
                )
                db.add(nq)
                db.flush()
                sent_ids.add(nq.id)

        for qid, q in existing.items():
            if qid not in sent_ids:
                db.delete(q)

    db.commit()
    db.expire_all()
    db.refresh(test)
    return get_test(test_id, db, me)

@router.post("/{test_id}/delete", dependencies=[Depends(require_role_any(["administrator", "teacher"]))])
def delete_test(test_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _ensure_teacher_or_admin(me, db)
    t = db.get(Test, test_id)
    if not t:
        raise HTTPException(status_code=404, detail="Test not found")
    db.delete(t)
    db.commit()
    return {"ok": True, "deleted_id": test_id}


@router.post("/{test_id}/assign", dependencies=[Depends(require_role_any(["administrator", "teacher"]))])
def assign_groups(test_id: int, payload: AssignGroupsIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _ensure_teacher_or_admin(me, db)
    t = db.get(Test, test_id)
    if not t:
        raise HTTPException(status_code=404, detail="Test not found")

    db.execute(delete(TestGroupAccess).where(TestGroupAccess.test_id == test_id))
    for gid in payload.group_ids:
        db.add(TestGroupAccess(test_id=test_id, group_id=gid))
    db.commit()
    return {"ok": True, "test_id": test_id, "group_ids": payload.group_ids}

@router.post("/{test_id}/start", response_model=StartOut, dependencies=[Depends(require_role_any(["student"]))])
def start_test(test_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    st = _student(db, me)
    test = db.get(Test, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    access = db.scalar(select(TestGroupAccess).where(TestGroupAccess.test_id == test_id, TestGroupAccess.group_id == st.group_id))
    if not access:
        raise HTTPException(status_code=403, detail="Нет доступа к тесту")

    can_start, reason, prev_count = can_start_attempt(db, test, st.id)
    if not can_start:
        raise HTTPException(status_code=400, detail=reason)

    attempt = TestAttempt(student_id=st.id, test_id=test.id, attempt_number=prev_count + 1, status=AttemptStatus.started)
    db.add(attempt)
    db.flush()

    token = make_attempt_token(attempt.id, st.id, test.id)
    attempt.attempt_token = token
    db.commit()
    db.refresh(attempt)

    must_finish_at = calc_must_finish_at(attempt.started_at, test.duration_minutes)
    if test.deadline and must_finish_at and must_finish_at > test.deadline:
        must_finish_at = test.deadline

    return StartOut(
        attempt_id=attempt.id,
        attempt_number=attempt.attempt_number,
        attempt_token=token,
        started_at=attempt.started_at,
        deadline_at=test.deadline,
        must_finish_at=must_finish_at
    )

@router.post("/{test_id}/submit", response_model=AttemptOut, dependencies=[Depends(require_role_any(["student"]))])
def submit_test(test_id: int, payload: SubmitIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    st = _student(db, me)
    attempt = db.get(TestAttempt, payload.attempt_id)
    if not attempt or attempt.student_id != st.id or attempt.test_id != test_id:
        raise HTTPException(status_code=404, detail="Attempt not found")

    if attempt.status != AttemptStatus.started:
        raise HTTPException(status_code=400, detail="Попытка уже завершена")

    if not (attempt.attempt_token and verify_attempt_token(payload.attempt_token, attempt.id, st.id, test_id)):
        raise HTTPException(status_code=400, detail="Некорректный токен")

    test = db.get(Test, test_id)
    now = datetime.utcnow()

    if test.deadline and now > test.deadline:
        attempt.status = AttemptStatus.expired
    elif test.duration_minutes:
        must_finish_at = attempt.started_at + timedelta(minutes=test.duration_minutes)
        if test.deadline and must_finish_at > test.deadline:
            must_finish_at = test.deadline
        if now > must_finish_at:
            attempt.status = AttemptStatus.expired

    if attempt.status == AttemptStatus.expired:
        attempt.finished_at = now
        attempt.answers = payload.answers
        db.commit()
        db.refresh(attempt)
        return attempt

    questions = db.scalars(select(Question).where(Question.test_id == test_id)).all()
    score = evaluate_auto(questions, payload.answers)

    attempt.answers = payload.answers
    attempt.auto_score = score
    attempt.status = AttemptStatus.submitted
    attempt.finished_at = now
    attempt.attempt_token = None
    db.commit()
    db.refresh(attempt)
    return attempt


@router.get(
    "/{test_id}/attempts",
    response_model=list[AttemptOut],
    dependencies=[Depends(require_role_any(["teacher", "administrator"]))],
)
def list_attempts(
    test_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _ensure_teacher_or_admin(me, db)

    attempts = (
        db.query(TestAttempt)
        .options(
            joinedload(TestAttempt.student)
            .joinedload(StudentModel.user),
            joinedload(TestAttempt.student)
            .joinedload(StudentModel.group),
        )
        .filter(TestAttempt.test_id == test_id)
        .order_by(TestAttempt.started_at.desc())
        .all()
    )

    result = []
    for a in attempts:
        result.append(
            AttemptOut(
                id=a.id,
                student_id=a.student_id,
                test_id=a.test_id,
                attempt_number=a.attempt_number,
                status=a.status,
                started_at=a.started_at,
                finished_at=a.finished_at,
                auto_score=a.auto_score,
                teacher_score=a.teacher_score,
                student_name=a.student.user.full_name
                if a.student and a.student.user
                else None,
                group_name=a.student.group.title
                if a.student and a.student.group
                else None,
            )
        )
    return result

@router.get(
    "/attempts/{attempt_id}",
    response_model=AttemptDetailOut,
    dependencies=[Depends(require_role_any(["teacher", "administrator", "student"]))],
)
def get_attempt(
    attempt_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    attempt = (
        db.query(TestAttempt)
        .options(
            joinedload(TestAttempt.student).joinedload(StudentModel.group),
            joinedload(TestAttempt.test).joinedload(Test.questions),
        )
        .filter(TestAttempt.id == attempt_id)
        .first()
    )
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    if not is_admin(me, db):
        teacher = db.scalar(select(Teacher).where(Teacher.user_id == me.id))
        if not teacher:
            st = _student(db, me)
            if st.id != attempt.student_id:
                raise HTTPException(status_code=403, detail="Нет доступа")

    result = AttemptDetailOut.from_orm(attempt)

    questions = attempt.test.questions

    result.answers = attempt.answers or {}
    result.correct_answers = {str(q.id): q.correct_answers for q in questions}

    from app.services.testing_service import (
        evaluate_auto_detailed,
        get_max_score_for_test,
    )

    detailed = evaluate_auto_detailed(questions, result.answers)
    result.detailed_scores = detailed
    result.total_score = sum(detailed.values())
    result.max_score = get_max_score_for_test(attempt.test)

    result.student_name = (
        attempt.student.user.full_name if attempt.student and attempt.student.user else None
    )
    result.group_name = (
        attempt.student.group.title if attempt.student and attempt.student.group else None
    )

    return result


@router.post("/attempts/{attempt_id}/review", response_model=AttemptOut, dependencies=[Depends(require_role_any(["teacher", "administrator"]))])
def review_attempt(attempt_id: int, payload: ReviewIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _ensure_teacher_or_admin(me, db)
    attempt = db.get(TestAttempt, attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.status not in (AttemptStatus.submitted, AttemptStatus.reviewed, AttemptStatus.expired):
        raise HTTPException(status_code=400, detail="Попытка не готова к проверке")

    attempt.teacher_score = payload.teacher_score
    attempt.review_comment = payload.comment
    attempt.reviewed_by_user_id = me.id
    attempt.status = AttemptStatus.reviewed
    db.commit()
    db.refresh(attempt)
    return attempt
