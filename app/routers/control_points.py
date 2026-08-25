from decimal import Decimal, ROUND_HALF_UP
from math import ceil

from fastapi import APIRouter, Depends, Header
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.orm.exc import StaleDataError

from app.core.deps import get_current_user, get_db
from app.models.grade import Student
from app.models.journal import (
    JournalAssignment,
    JournalControlPoint,
    JournalControlPointScore,
    JournalEntry,
    JournalLesson,
    JournalLessonStudent,
    JournalPeriod,
)
from app.models.schedule import Group, Subject, Teacher
from app.models.user import User
from app.schemas.journal import (
    ControlPointBatchPut,
    ControlPointPatch,
    ControlPointScorePut,
    ControlPointsGenerate,
)
from app.services.journal_service import (
    JournalAPIError,
    add_audit,
    ensure_pair_access,
    ensure_permission,
    ensure_unlocked,
    error,
    get_or_create_period,
    is_privileged,
    student_full_name,
)


router = APIRouter(prefix="/api/v1/journal/control-points", tags=["journal-control-points"])

ATTENDANCE_MAX = {1: Decimal("3"), 2: Decimal("3"), 3: Decimal("4")}
CURRENT_MAX = Decimal("20")
PROJECT_SEMESTER_MAX = Decimal("20")
EXCLUDED_COMPONENTS = {"industrial_practice", "coursework"}


def _decimal(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _score_out(score: JournalControlPointScore) -> dict:
    total = score.current_score + score.attendance_score + score.project_score
    return {
        "id": score.id,
        "control_point_id": score.control_point_id,
        "student_id": score.student_id,
        "current_score": float(score.current_score),
        "attendance_score": float(score.attendance_score),
        "calculated_attendance_score": float(score.calculated_attendance_score),
        "attendance_is_manual": score.attendance_is_manual,
        "eligible_lessons": score.eligible_lessons,
        "attended_lessons": score.attended_lessons,
        "project_score": float(score.project_score),
        "total_score": float(total),
        "comment": score.comment,
        "version": score.version,
    }


def _control_point_out(point: JournalControlPoint, include_scores: bool = False) -> dict:
    payload = {
        "id": point.id,
        "group_id": point.group_id,
        "subject_id": point.subject_id,
        "teacher_id": point.teacher_id,
        "period_id": point.period_id,
        "number": point.number,
        "planned_lesson_number": point.planned_lesson_number,
        "planned_date": point.planned_date.isoformat() if point.planned_date else None,
        "journal_lesson_id": point.journal_lesson_id,
        "total_practical_hours": point.total_practical_hours,
        "hours_per_lesson": point.hours_per_lesson,
        "current_max": float(point.current_max),
        "attendance_max": float(point.attendance_max),
        "base_max": float(point.current_max + point.attendance_max),
        "project_semester_max": float(point.project_semester_max),
        "status": point.status,
        "version": point.version,
    }
    if include_scores:
        payload["scores"] = [_score_out(row) for row in point.scores]
    return payload


def _point_state(point: JournalControlPoint) -> dict:
    return {
        "number": point.number,
        "planned_lesson_number": point.planned_lesson_number,
        "planned_date": point.planned_date.isoformat() if point.planned_date else None,
        "journal_lesson_id": point.journal_lesson_id,
        "status": point.status,
        "version": point.version,
    }


def _score_state(score: JournalControlPointScore | None) -> dict | None:
    if score is None:
        return None
    return {
        "current_score": float(score.current_score),
        "attendance_score": float(score.attendance_score),
        "calculated_attendance_score": float(score.calculated_attendance_score),
        "project_score": float(score.project_score),
        "comment": score.comment,
        "version": score.version,
    }


def _load_point(db: Session, point_id: int) -> JournalControlPoint:
    point = db.scalar(
        select(JournalControlPoint)
        .options(
            joinedload(JournalControlPoint.period),
            joinedload(JournalControlPoint.subject),
            selectinload(JournalControlPoint.scores),
        )
        .where(JournalControlPoint.id == point_id)
    )
    if not point:
        error(404, "JOURNAL_CONTROL_POINT_NOT_FOUND", "Контрольная точка не найдена")
    return point


def _ensure_point_access(db: Session, me: User, point: JournalControlPoint, write: bool = False):
    ensure_permission(db, me, "journal.entry.write" if write else "journal.read")
    ensure_pair_access(
        db,
        me,
        point.group_id,
        point.subject_id,
        point.period.academic_year,
        point.period.semester,
    )
    if write:
        ensure_unlocked(point.period)
        if point.status == "locked":
            error(423, "JOURNAL_CONTROL_POINT_LOCKED", "Контрольная точка закрыта")


def _period_lessons(db: Session, point: JournalControlPoint) -> list[JournalLesson]:
    return db.scalars(
        select(JournalLesson)
        .where(
            JournalLesson.group_id == point.group_id,
            JournalLesson.subject_id == point.subject_id,
            JournalLesson.lesson_date >= point.period.starts_on,
            JournalLesson.lesson_date <= point.period.ends_on,
            JournalLesson.lesson_type.in_(("practice", "lab")),
            JournalLesson.status != "cancelled",
        )
        .order_by(JournalLesson.lesson_date, JournalLesson.starts_at, JournalLesson.id)
    ).all()


def _segment_lessons(
    db: Session, point: JournalControlPoint, all_points: list[JournalControlPoint] | None = None
) -> list[JournalLesson]:
    lessons = _period_lessons(db, point)
    points = all_points or db.scalars(
        select(JournalControlPoint)
        .where(
            JournalControlPoint.group_id == point.group_id,
            JournalControlPoint.subject_id == point.subject_id,
            JournalControlPoint.period_id == point.period_id,
        )
        .order_by(JournalControlPoint.number)
    ).all()
    previous_end = 0
    for row in points:
        if row.number < point.number:
            previous_end = max(previous_end, row.planned_lesson_number)
    return lessons[previous_end : point.planned_lesson_number]


def _calculate_attendance(
    db: Session,
    point: JournalControlPoint,
    student_id: int,
    all_points: list[JournalControlPoint] | None = None,
) -> tuple[int, int, Decimal]:
    lessons = _segment_lessons(db, point, all_points)
    lesson_ids = [row.id for row in lessons]
    eligible = len(lesson_ids)
    if eligible == 0:
        return 0, 0, Decimal("0.00")
    absent_count = db.scalar(
        select(func.count(JournalEntry.id)).where(
            JournalEntry.lesson_id.in_(lesson_ids),
            JournalEntry.student_id == student_id,
            JournalEntry.attendance == "absent",
        )
    ) or 0
    attended = max(0, eligible - absent_count)
    calculated = (
        point.attendance_max * Decimal(attended) / Decimal(eligible)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return eligible, attended, calculated


def _student_allowed(db: Session, point: JournalControlPoint, student_id: int) -> bool:
    current = db.scalar(
        select(Student.id).where(Student.id == student_id, Student.group_id == point.group_id)
    )
    if current:
        return True
    return bool(
        db.scalar(
            select(JournalLessonStudent.id)
            .join(JournalLesson, JournalLesson.id == JournalLessonStudent.lesson_id)
            .where(
                JournalLessonStudent.student_id == student_id,
                JournalLesson.group_id == point.group_id,
                JournalLesson.subject_id == point.subject_id,
                JournalLesson.period_id == point.period_id,
            )
            .limit(1)
        )
    )


def _semester_project_total(
    db: Session, point: JournalControlPoint, student_id: int, exclude_score_id: int | None = None
) -> Decimal:
    query = (
        select(func.coalesce(func.sum(JournalControlPointScore.project_score), 0))
        .join(
            JournalControlPoint,
            JournalControlPoint.id == JournalControlPointScore.control_point_id,
        )
        .where(
            JournalControlPoint.group_id == point.group_id,
            JournalControlPoint.subject_id == point.subject_id,
            JournalControlPoint.period_id == point.period_id,
            JournalControlPointScore.student_id == student_id,
        )
    )
    if exclude_score_id is not None:
        query = query.where(JournalControlPointScore.id != exclude_score_id)
    return _decimal(db.scalar(query) or 0)


@router.post(":generate", status_code=201)
def generate_control_points(
    payload: ControlPointsGenerate,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    ensure_permission(db, me, "journal.lesson.write")
    if payload.study_component in EXCLUDED_COMPONENTS:
        error(
            422,
            "JOURNAL_CONTROL_POINTS_NOT_APPLICABLE",
            "Для производственной практики и курсовых работ КТ не формируются",
        )
    group = db.get(Group, payload.group_id)
    subject = db.get(Subject, payload.subject_id)
    if not group or not subject:
        error(404, "JOURNAL_NOT_FOUND", "Группа или дисциплина не найдена")
    period = get_or_create_period(db, payload.academic_year, payload.semester)
    ensure_unlocked(period)
    current_teacher = ensure_pair_access(
        db,
        me,
        payload.group_id,
        payload.subject_id,
        payload.academic_year,
        payload.semester,
    )
    if current_teacher:
        teacher = current_teacher
        if payload.teacher_id and payload.teacher_id != teacher.id:
            error(403, "JOURNAL_ACCESS_DENIED", "Нельзя назначить другого преподавателя")
    else:
        teacher = db.get(Teacher, payload.teacher_id) if payload.teacher_id else None
        if not teacher:
            teacher = db.scalar(
                select(Teacher)
                .join(JournalAssignment, JournalAssignment.teacher_id == Teacher.id)
                .where(
                    JournalAssignment.group_id == payload.group_id,
                    JournalAssignment.subject_id == payload.subject_id,
                    JournalAssignment.academic_year == payload.academic_year,
                    JournalAssignment.semester == payload.semester,
                    JournalAssignment.is_active.is_(True),
                )
                .limit(1)
            )
        if not teacher:
            error(422, "JOURNAL_TEACHER_REQUIRED", "Для КТ не назначен преподаватель")

    lesson_count = ceil(payload.total_practical_hours / payload.hours_per_lesson)
    interval = ceil(lesson_count / 3)
    positions = [min(interval, lesson_count), min(interval * 2, lesson_count), lesson_count]
    lessons = db.scalars(
        select(JournalLesson)
        .where(
            JournalLesson.group_id == payload.group_id,
            JournalLesson.subject_id == payload.subject_id,
            JournalLesson.lesson_date >= period.starts_on,
            JournalLesson.lesson_date <= period.ends_on,
            JournalLesson.lesson_type.in_(("practice", "lab")),
            JournalLesson.status != "cancelled",
        )
        .order_by(JournalLesson.lesson_date, JournalLesson.starts_at, JournalLesson.id)
    ).all()
    existing = {
        row.number: row
        for row in db.scalars(
            select(JournalControlPoint)
            .where(
                JournalControlPoint.group_id == payload.group_id,
                JournalControlPoint.subject_id == payload.subject_id,
                JournalControlPoint.period_id == period.id,
            )
        ).all()
    }
    points: list[JournalControlPoint] = []
    for number, position in enumerate(positions, start=1):
        point = existing.get(number)
        if point and point.status == "locked":
            error(423, "JOURNAL_CONTROL_POINT_LOCKED", "Нельзя пересчитать закрытую КТ")
        actual_lesson = lessons[position - 1] if len(lessons) >= position else None
        if point is None:
            point = JournalControlPoint(
                group_id=payload.group_id,
                subject_id=payload.subject_id,
                teacher_id=teacher.id,
                period_id=period.id,
                number=number,
                planned_lesson_number=position,
                total_practical_hours=payload.total_practical_hours,
                hours_per_lesson=payload.hours_per_lesson,
                current_max=CURRENT_MAX,
                attendance_max=ATTENDANCE_MAX[number],
                project_semester_max=PROJECT_SEMESTER_MAX,
                created_by=me.id,
                updated_by=me.id,
            )
            db.add(point)
            db.flush()
            add_audit(
                db, me, "control_point", point.id, "create", None, _point_state(point),
                lesson_id=actual_lesson.id if actual_lesson else None,
                request_id=request_id,
            )
        else:
            before = _point_state(point)
            point.teacher_id = teacher.id
            point.planned_lesson_number = position
            point.total_practical_hours = payload.total_practical_hours
            point.hours_per_lesson = payload.hours_per_lesson
            point.attendance_max = ATTENDANCE_MAX[number]
            point.version += 1
            point.updated_by = me.id
            add_audit(
                db, me, "control_point", point.id, "recalculate", before, _point_state(point),
                lesson_id=actual_lesson.id if actual_lesson else None,
                request_id=request_id,
            )
        point.journal_lesson_id = actual_lesson.id if actual_lesson else None
        point.planned_date = actual_lesson.lesson_date if actual_lesson else None
        points.append(point)

    students = db.scalars(
        select(Student).options(joinedload(Student.user)).where(Student.group_id == group.id)
    ).unique().all()
    for point in points:
        existing_student_ids = set(
            db.scalars(
                select(JournalControlPointScore.student_id).where(
                    JournalControlPointScore.control_point_id == point.id
                )
            ).all()
        )
        for student in students:
            if student.id not in existing_student_ids:
                db.add(
                    JournalControlPointScore(
                        control_point_id=point.id,
                        student_id=student.id,
                        updated_by=me.id,
                    )
                )
    try:
        db.commit()
    except (IntegrityError, StaleDataError):
        db.rollback()
        error(409, "JOURNAL_CONTROL_POINT_CONFLICT", "КТ уже были изменены")
    return {
        "lesson_count": lesson_count,
        "interval": interval,
        "formula": f"ceil(({payload.total_practical_hours}/{payload.hours_per_lesson})/3)",
        "items": [_control_point_out(row) for row in points],
    }


@router.get("")
def list_control_points(
    group_id: int,
    subject_id: int,
    academic_year: int,
    semester: str,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    ensure_permission(db, me, "journal.read")
    ensure_pair_access(db, me, group_id, subject_id, academic_year, semester)
    period = db.scalar(
        select(JournalPeriod).where(
            JournalPeriod.academic_year == academic_year,
            JournalPeriod.semester == semester,
        )
    )
    if not period:
        return {"items": []}
    points = db.scalars(
        select(JournalControlPoint)
        .options(selectinload(JournalControlPoint.scores))
        .where(
            JournalControlPoint.group_id == group_id,
            JournalControlPoint.subject_id == subject_id,
            JournalControlPoint.period_id == period.id,
        )
        .order_by(JournalControlPoint.number)
    ).all()
    return {"items": [_control_point_out(row, include_scores=True) for row in points]}


@router.get("/statement")
def control_point_statement(
    group_id: int,
    subject_id: int,
    academic_year: int,
    semester: str,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    ensure_permission(db, me, "journal.read")
    ensure_pair_access(db, me, group_id, subject_id, academic_year, semester)
    group = db.get(Group, group_id)
    subject = db.get(Subject, subject_id)
    period = db.scalar(
        select(JournalPeriod).where(
            JournalPeriod.academic_year == academic_year,
            JournalPeriod.semester == semester,
        )
    )
    if not group or not subject or not period:
        error(404, "JOURNAL_CONTROL_POINT_NOT_FOUND", "Ведомость КТ не найдена")
    points = db.scalars(
        select(JournalControlPoint)
        .options(selectinload(JournalControlPoint.scores))
        .where(
            JournalControlPoint.group_id == group_id,
            JournalControlPoint.subject_id == subject_id,
            JournalControlPoint.period_id == period.id,
        )
        .order_by(JournalControlPoint.number)
    ).all()
    students = db.scalars(
        select(Student).options(joinedload(Student.user)).where(Student.group_id == group_id)
    ).unique().all()
    students.sort(key=student_full_name)
    score_map = {
        (point.number, score.student_id): score
        for point in points
        for score in point.scores
    }
    rows = []
    for student in students:
        point_rows = []
        current_total = Decimal("0")
        attendance_total = Decimal("0")
        project_total = Decimal("0")
        for number in (1, 2, 3):
            score = score_map.get((number, student.id))
            item = _score_out(score) if score else {
                "current_score": 0.0,
                "attendance_score": 0.0,
                "project_score": 0.0,
                "total_score": 0.0,
            }
            point_rows.append({"number": number, **item})
            if score:
                current_total += score.current_score
                attendance_total += score.attendance_score
                project_total += score.project_score
        rows.append(
            {
                "student": {
                    "id": student.id,
                    "full_name": student_full_name(student),
                    "record_book": student.record_book,
                },
                "control_points": point_rows,
                "current_total": float(current_total),
                "attendance_total": float(attendance_total),
                "project_total": float(project_total),
                "semester_total": float(current_total + attendance_total + project_total),
            }
        )
    return {
        "group": {"id": group.id, "code": group.code},
        "subject": {"id": subject.id, "code": subject.code, "title": subject.title},
        "period": {"id": period.id, "academic_year": academic_year, "semester": semester},
        "maximums": {
            "current": 60,
            "attendance": 10,
            "project": 20,
            "semester_total": 90,
            "control_points": [23, 23, 24],
        },
        "attendance_policy": {
            "type": "proportional_absence",
            "formula": "attendance_max * (eligible_lessons - absences) / eligible_lessons",
            "note": "Ручная корректировка сохраняется до пересчёта с reset_manual=true",
        },
        "items": rows,
    }


@router.patch("/{point_id}")
def patch_control_point(
    point_id: int,
    payload: ControlPointPatch,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    point = _load_point(db, point_id)
    ensure_permission(db, me, "journal.lesson.write")
    ensure_pair_access(
        db, me, point.group_id, point.subject_id,
        point.period.academic_year, point.period.semester,
    )
    ensure_unlocked(point.period)
    if payload.version != point.version:
        error(409, "JOURNAL_VERSION_CONFLICT", "КТ уже изменена", {"current": _control_point_out(point)})
    if point.status == "locked" and payload.status != "published":
        error(423, "JOURNAL_CONTROL_POINT_LOCKED", "Сначала откройте КТ")
    before = _point_state(point)
    for field in payload.model_fields_set - {"version"}:
        setattr(point, field, getattr(payload, field))
    if point.journal_lesson_id:
        lesson = db.get(JournalLesson, point.journal_lesson_id)
        if not lesson or lesson.group_id != point.group_id or lesson.subject_id != point.subject_id:
            error(422, "JOURNAL_CONTROL_POINT_LESSON_MISMATCH", "Занятие не относится к журналу")
        point.planned_date = lesson.lesson_date
    point.version += 1
    point.updated_by = me.id
    add_audit(
        db, me, "control_point", point.id, "update", before, _point_state(point),
        lesson_id=point.journal_lesson_id, request_id=request_id,
    )
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        error(409, "JOURNAL_VERSION_CONFLICT", "КТ уже изменена")
    return _control_point_out(point)


def _save_score(
    db: Session,
    me: User,
    point: JournalControlPoint,
    student_id: int,
    payload: ControlPointScorePut,
    request_id: str | None,
) -> JournalControlPointScore:
    if not _student_allowed(db, point, student_id):
        error(422, "JOURNAL_STUDENT_NOT_IN_GROUP", "Студент не относится к журналу")
    score = db.scalar(
        select(JournalControlPointScore).where(
            JournalControlPointScore.control_point_id == point.id,
            JournalControlPointScore.student_id == student_id,
        )
    )
    if score and payload.version != score.version:
        error(409, "JOURNAL_VERSION_CONFLICT", "Баллы уже изменены", {"current": _score_out(score)})
    if not score and payload.version not in {0, 1}:
        error(409, "JOURNAL_VERSION_CONFLICT", "Запись баллов ещё не существует")
    project_score = _decimal(payload.project_score)
    other_project = _semester_project_total(
        db, point, student_id, score.id if score else None
    )
    if other_project + project_score > PROJECT_SEMESTER_MAX:
        error(
            422,
            "JOURNAL_PROJECT_SCORE_LIMIT",
            "Суммарный проектный балл за семестр не может превышать 20",
            {"already_awarded": float(other_project), "requested": float(project_score)},
        )
    eligible, attended, calculated = _calculate_attendance(db, point, student_id)
    before = _score_state(score)
    if score is None:
        score = JournalControlPointScore(
            control_point_id=point.id,
            student_id=student_id,
            updated_by=me.id,
        )
        db.add(score)
        db.flush()
        operation = "create"
    else:
        score.version += 1
        operation = "update"
    score.current_score = _decimal(payload.current_score)
    score.project_score = project_score
    score.calculated_attendance_score = calculated
    score.eligible_lessons = eligible
    score.attended_lessons = attended
    if payload.attendance_score is None:
        score.attendance_score = calculated
        score.attendance_is_manual = False
    else:
        attendance_score = _decimal(payload.attendance_score)
        if attendance_score > point.attendance_max:
            error(
                422,
                "JOURNAL_ATTENDANCE_SCORE_LIMIT",
                f"Для КТ №{point.number} максимум {point.attendance_max} балла",
            )
        score.attendance_score = attendance_score
        score.attendance_is_manual = True
    score.comment = payload.comment
    score.updated_by = me.id
    add_audit(
        db, me, "control_point_score", score.id, operation, before, _score_state(score),
        lesson_id=point.journal_lesson_id, student_id=student_id, request_id=request_id,
    )
    return score


@router.put("/{point_id}/scores/{student_id}")
def put_control_point_score(
    point_id: int,
    student_id: int,
    payload: ControlPointScorePut,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    point = _load_point(db, point_id)
    _ensure_point_access(db, me, point, write=True)
    score = _save_score(db, me, point, student_id, payload, request_id)
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        error(409, "JOURNAL_VERSION_CONFLICT", "Баллы уже изменены")
    except IntegrityError:
        db.rollback()
        error(409, "JOURNAL_CONTROL_POINT_SCORE_CONFLICT", "Запись баллов уже создана")
    db.refresh(score)
    return _score_out(score)


@router.put("/{point_id}/scores:batch")
def put_control_point_scores_batch(
    point_id: int,
    payload: ControlPointBatchPut,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    point = _load_point(db, point_id)
    _ensure_point_access(db, me, point, write=True)
    updated = []
    failed = []
    seen = set()
    for item in payload.scores:
        if item.student_id in seen:
            failed.append({
                "student_id": item.student_id,
                "code": "JOURNAL_DUPLICATE_STUDENT",
                "message": "Студент повторяется в batch-запросе",
            })
            continue
        seen.add(item.student_id)
        try:
            with db.begin_nested():
                score = _save_score(db, me, point, item.student_id, item, request_id)
                db.flush()
            updated.append(score)
        except (JournalAPIError, StaleDataError, IntegrityError) as exc:
            if isinstance(exc, JournalAPIError):
                data = exc.detail["error"]
            elif isinstance(exc, StaleDataError):
                data = {"code": "JOURNAL_VERSION_CONFLICT", "message": "Баллы уже изменены"}
            else:
                data = {"code": "JOURNAL_CONTROL_POINT_SCORE_CONFLICT", "message": "Конфликт записи"}
            failed.append({
                "student_id": item.student_id,
                "code": data["code"],
                "message": data["message"],
            })
    db.commit()
    return {"updated": [_score_out(row) for row in updated], "failed": failed}


@router.post("/{point_id}/attendance:recalculate")
def recalculate_control_point_attendance(
    point_id: int,
    reset_manual: bool = False,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    point = _load_point(db, point_id)
    _ensure_point_access(db, me, point, write=True)
    changed = 0
    for score in point.scores:
        before = _score_state(score)
        eligible, attended, calculated = _calculate_attendance(db, point, score.student_id)
        score.eligible_lessons = eligible
        score.attended_lessons = attended
        score.calculated_attendance_score = calculated
        if reset_manual or not score.attendance_is_manual:
            score.attendance_score = calculated
            score.attendance_is_manual = False
        score.version += 1
        score.updated_by = me.id
        add_audit(
            db, me, "control_point_score", score.id, "attendance_recalculate",
            before, _score_state(score), lesson_id=point.journal_lesson_id,
            student_id=score.student_id, request_id=request_id,
        )
        changed += 1
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        error(409, "JOURNAL_VERSION_CONFLICT", "Ведомость уже изменена")
    return {"control_point_id": point.id, "updated": changed}
