from datetime import date
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.orm.exc import StaleDataError

from app.core.deps import get_current_user, get_db
from app.models.grade import Student
from app.models.journal import (
    JournalAssignment,
    JournalEntry,
    JournalLesson,
    JournalLessonStudent,
    JournalPeriod,
    SubjectTopic,
)
from app.models.schedule import Group, Lesson, Subject, Teacher
from app.models.user import User
from app.schemas.journal import (
    JournalBatchPut,
    JournalEntryPut,
    JournalLessonCreate,
    JournalLessonPatch,
    LessonType,
)
from app.services.journal_service import (
    JournalAPIError,
    add_audit,
    ensure_lesson_access,
    ensure_journal_read_access,
    ensure_pair_access,
    ensure_permission,
    ensure_unlocked,
    entry_state,
    error,
    get_or_create_period,
    get_student,
    get_teacher,
    grade_scale,
    has_permission,
    is_privileged,
    lesson_state,
    period_bounds,
    period_for_date,
    period_key_for_date,
    student_full_name,
    teacher_has_assignment,
    validate_grade,
)
from app.services.journal_export import JOURNAL_EXPORT_MEDIA_TYPE, build_journal_workbook
from app.services.subject_teacher_service import (
    subject_teacher_payload,
    teacher_is_linked_to_subject,
)


router = APIRouter(prefix="/api/v1/journal", tags=["journal"])


def _student_out(student: Student) -> dict:
    return {
        "id": student.id,
        "full_name": student_full_name(student),
        "record_book": student.record_book,
        "status": "active",
    }


def _lesson_out(lesson: JournalLesson) -> dict:
    return {
        "id": lesson.id,
        "group_id": lesson.group_id,
        "subject_id": lesson.subject_id,
        "teacher_id": lesson.teacher_id,
        "date": lesson.lesson_date.isoformat(),
        "hours": lesson.hours,
        "starts_at": lesson.starts_at.isoformat() if lesson.starts_at else None,
        "ends_at": lesson.ends_at.isoformat() if lesson.ends_at else None,
        "type": lesson.lesson_type,
        "topic": (
            {"id": lesson.topic.id, "title": lesson.topic.title} if lesson.topic else None
        ),
        "topic_text": lesson.topic_text,
        "comment": lesson.comment,
        "schedule_lesson_id": lesson.schedule_lesson_id,
        "source": "schedule" if lesson.schedule_lesson_id else "manual",
        "status": lesson.status,
        "version": lesson.version,
    }


def _journal_days(lessons: list[JournalLesson]) -> list[dict]:
    days_by_date: dict[str, dict] = {}
    for lesson in lessons:
        date_key = lesson.lesson_date.isoformat()
        day = days_by_date.setdefault(date_key, {"date": date_key, "lessons": []})
        lesson_payload = _lesson_out(lesson)
        lesson_payload.pop("date", None)
        day["lessons"].append(lesson_payload)
    return list(days_by_date.values())


def _entry_out(entry: JournalEntry) -> dict:
    return {
        "id": entry.id,
        "lesson_id": entry.lesson_id,
        "student_id": entry.student_id,
        "attendance": entry.attendance,
        "grade": entry.grade,
        "comment": entry.comment,
        "version": entry.version,
    }


def _request_id(request_id: str | None) -> str | None:
    return request_id[:100] if request_id else None


def _lesson_create_conflict(
    db: Session,
    me: User,
    idempotency_key: str | None,
    schedule_lesson_id: int | None,
) -> dict:
    if idempotency_key:
        existing = db.scalar(
            select(JournalLesson)
            .options(joinedload(JournalLesson.topic), joinedload(JournalLesson.period))
            .where(JournalLesson.idempotency_key == idempotency_key)
        )
        if existing:
            ensure_lesson_access(db, me, existing)
            return _lesson_out(existing)
    if schedule_lesson_id is not None:
        linked_lesson_id = db.scalar(
            select(JournalLesson.id).where(
                JournalLesson.schedule_lesson_id == schedule_lesson_id
            )
        )
        if linked_lesson_id:
            error(
                409,
                "JOURNAL_LESSON_DUPLICATE",
                "Занятие расписания уже добавлено в журнал",
                {"journal_lesson_id": linked_lesson_id},
            )
    error(409, "JOURNAL_LESSON_CONFLICT", "Не удалось создать занятие")


def _student_viewer(db: Session, user: User) -> Student | None:
    if is_privileged(db, user) or get_teacher(db, user, required=False) is not None:
        return None
    if get_student(db, user, required=False) is not None:
        error(403, "JOURNAL_ACCESS_DENIED", "Студентам учебный журнал недоступен")
    return None


@router.get("/catalog")
def journal_catalog(
    academic_year: int,
    semester: str,
    teacher_id: int | None = None,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    ensure_permission(db, me, "journal.read")
    period_bounds(academic_year, semester)
    privileged = is_privileged(db, me)
    student_viewer = _student_viewer(db, me)
    if teacher_id is not None and not privileged:
        error(403, "JOURNAL_ACCESS_DENIED", "teacher_id доступен только администратору")

    if student_viewer is not None:
        selected_teacher_id = None
    elif privileged:
        selected_teacher_id = teacher_id
    else:
        selected_teacher_id = get_teacher(db, me).id

    assignment_query = (
        select(JournalAssignment)
        .options(
            joinedload(JournalAssignment.group),
            joinedload(JournalAssignment.subject).selectinload(Subject.teachers),
            joinedload(JournalAssignment.subject).joinedload(Subject.primary_teacher),
        )
        .where(
            JournalAssignment.academic_year == academic_year,
            JournalAssignment.semester == semester,
            JournalAssignment.is_active.is_(True),
        )
    )
    if student_viewer is not None:
        assignment_query = assignment_query.where(
            JournalAssignment.group_id == student_viewer.group_id
        )
    if selected_teacher_id is not None:
        assignment_query = assignment_query.where(
            JournalAssignment.teacher_id == selected_teacher_id
        )
    assignments = db.scalars(assignment_query).unique().all()

    pairs: dict[tuple[int, int], tuple[Group, Subject]] = {
        (row.group_id, row.subject_id): (row.group, row.subject) for row in assignments
    }

    group_ids = {group_id for group_id, _ in pairs}
    student_counts = dict(
        db.execute(
            select(Student.group_id, func.count(Student.id))
            .where(Student.group_id.in_(group_ids) if group_ids else False)
            .group_by(Student.group_id)
        ).all()
    )
    grouped: dict[int, dict] = {}
    for (group_id, _subject_id), (group, subject) in sorted(
        pairs.items(), key=lambda item: (item[1][0].code, item[1][1].title)
    ):
        group_payload = grouped.setdefault(
            group_id,
            {
                "id": group.id,
                "code": group.code,
                "student_count": student_counts.get(group.id, 0),
                "subjects": [],
            },
        )
        group_payload["subjects"].append(
            {
                "id": subject.id,
                "code": subject.code,
                "title": subject.title,
                "grade_scale": grade_scale(subject),
                **subject_teacher_payload(subject),
            }
        )
    return {
        "academic_year": academic_year,
        "semester": semester,
        "access_scope": "self" if student_viewer is not None else "group",
        "groups": list(grouped.values()),
    }


@router.get("/groups/{group_id}/students")
def journal_group_students(
    group_id: int,
    on_date: date | None = None,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    ensure_permission(db, me, "journal.read")
    group = db.get(Group, group_id)
    if not group:
        error(404, "JOURNAL_GROUP_NOT_FOUND", "Группа не найдена")

    student_viewer = _student_viewer(db, me)
    if student_viewer is not None:
        if student_viewer.group_id != group_id:
            error(403, "JOURNAL_ACCESS_DENIED", "Студенту доступна только его группа")
        return {"group_id": group_id, "items": [_student_out(student_viewer)]}

    if not is_privileged(db, me):
        teacher = get_teacher(db, me)
        academic_year, semester = period_key_for_date(on_date or date.today())
        assigned = db.scalar(
            select(JournalAssignment.id).where(
                JournalAssignment.teacher_id == teacher.id,
                JournalAssignment.group_id == group_id,
                JournalAssignment.academic_year == academic_year,
                JournalAssignment.semester == semester,
                JournalAssignment.is_active.is_(True),
            ).limit(1)
        )
        if not assigned:
            error(403, "JOURNAL_ACCESS_DENIED", "Группа не назначена преподавателю")

    snapshot_ids: list[int] = []
    if on_date:
        snapshot_ids = db.scalars(
            select(JournalLessonStudent.student_id)
            .join(JournalLesson, JournalLesson.id == JournalLessonStudent.lesson_id)
            .where(JournalLesson.group_id == group_id, JournalLesson.lesson_date == on_date)
            .distinct()
        ).all()
    query = select(Student).options(joinedload(Student.user))
    query = query.where(
        Student.id.in_(snapshot_ids) if snapshot_ids else Student.group_id == group_id
    )
    students = db.scalars(query).unique().all()
    students.sort(key=student_full_name)
    return {"group_id": group_id, "items": [_student_out(row) for row in students]}


@router.get("/export", summary="Скачать учебный журнал в Excel")
def export_journal_excel(
    group_id: int,
    subject_id: int,
    date_from: date,
    date_to: date,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    ensure_permission(db, me, "journal.read")
    if date_to < date_from:
        error(422, "JOURNAL_INVALID_DATE_RANGE", "date_to должен быть не раньше date_from")
    group = db.get(Group, group_id)
    subject = db.get(Subject, subject_id)
    if not group or not subject:
        error(404, "JOURNAL_NOT_FOUND", "Группа или дисциплина не найдена")

    academic_year, semester = period_key_for_date(date_from)
    student_viewer = ensure_journal_read_access(
        db, me, group_id, subject_id, academic_year, semester
    )

    lesson_query = (
        select(JournalLesson)
        .options(
            joinedload(JournalLesson.topic),
            selectinload(JournalLesson.entries),
            selectinload(JournalLesson.student_snapshots),
        )
        .where(
            JournalLesson.group_id == group_id,
            JournalLesson.subject_id == subject_id,
            JournalLesson.lesson_date >= date_from,
            JournalLesson.lesson_date <= date_to,
        )
        .order_by(
            JournalLesson.lesson_date,
            JournalLesson.starts_at.is_(None),
            JournalLesson.starts_at,
            JournalLesson.id,
        )
    )
    if student_viewer is not None:
        lesson_query = lesson_query.where(JournalLesson.status == "published")
    lessons = db.scalars(lesson_query).unique().all()

    snapshot_ids = {
        row.student_id for lesson in lessons for row in lesson.student_snapshots
    }
    current_ids = set(
        db.scalars(select(Student.id).where(Student.group_id == group_id)).all()
    )
    student_ids = snapshot_ids | current_ids
    if student_viewer is not None:
        students = [student_viewer]
        entries = [
            entry
            for lesson in lessons
            for entry in lesson.entries
            if entry.student_id == student_viewer.id
        ]
    else:
        students = db.scalars(
            select(Student)
            .options(joinedload(Student.user))
            .where(Student.id.in_(student_ids) if student_ids else False)
        ).unique().all()
        entries = [entry for lesson in lessons for entry in lesson.entries]

    content = build_journal_workbook(
        group=group,
        subject=subject,
        date_from=date_from,
        date_to=date_to,
        students=students,
        lessons=lessons,
        entries=entries,
    )
    name_part = re.sub(r"[^\w.-]+", "_", group.code or str(group.id)).strip("_.")
    filename = (
        f"Учебный_журнал_{name_part}_{date_from.isoformat()}_{date_to.isoformat()}.xlsx"
    )
    encoded_filename = quote(filename)
    return Response(
        content=content,
        media_type=JOURNAL_EXPORT_MEDIA_TYPE,
        headers={
            "Content-Disposition": (
                f'attachment; filename="study_journal.xlsx"; filename*=UTF-8\'\'{encoded_filename}'
            )
        },
    )


@router.get("")
def get_journal(
    group_id: int,
    subject_id: int,
    date_from: date,
    date_to: date,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
    type: LessonType | None = None,
):
    ensure_permission(db, me, "journal.read")
    if date_to < date_from:
        error(422, "JOURNAL_INVALID_DATE_RANGE", "date_to должен быть не раньше date_from")
    group = db.get(Group, group_id)
    subject = db.scalar(
        select(Subject)
        .options(selectinload(Subject.teachers), joinedload(Subject.primary_teacher))
        .where(Subject.id == subject_id)
    )
    if not group or not subject:
        error(404, "JOURNAL_NOT_FOUND", "Группа или дисциплина не найдена")

    academic_year, semester = period_key_for_date(date_from)
    student_viewer = ensure_journal_read_access(
        db, me, group_id, subject_id, academic_year, semester
    )
    period = db.scalar(
        select(JournalPeriod).where(
            JournalPeriod.academic_year == academic_year,
            JournalPeriod.semester == semester,
        )
    )
    if period is None:
        period = get_or_create_period(db, academic_year, semester)
        db.commit()
        db.refresh(period)

    query = (
        select(JournalLesson)
        .options(
            joinedload(JournalLesson.topic),
            joinedload(JournalLesson.period),
            selectinload(JournalLesson.entries),
            selectinload(JournalLesson.student_snapshots),
        )
        .where(
            JournalLesson.group_id == group_id,
            JournalLesson.subject_id == subject_id,
            JournalLesson.lesson_date >= date_from,
            JournalLesson.lesson_date <= date_to,
        )
        .order_by(JournalLesson.lesson_date, JournalLesson.starts_at, JournalLesson.id)
    )
    if student_viewer is not None:
        query = query.where(JournalLesson.status == "published")
    if type is not None:
        query = query.where(JournalLesson.lesson_type == type)
    lessons = db.scalars(query).unique().all()

    snapshot_ids = {
        row.student_id for lesson in lessons for row in lesson.student_snapshots
    }
    current_ids = set(
        db.scalars(select(Student.id).where(Student.group_id == group_id)).all()
    )
    student_ids = snapshot_ids | current_ids
    if student_viewer is not None:
        students = [student_viewer]
    else:
        students = db.scalars(
            select(Student)
            .options(joinedload(Student.user))
            .where(Student.id.in_(student_ids) if student_ids else False)
        ).unique().all()
    students.sort(key=student_full_name)
    entries = [
        entry
        for lesson in lessons
        for entry in lesson.entries
        if student_viewer is None or entry.student_id == student_viewer.id
    ]

    return {
        "group": {"id": group.id, "code": group.code},
        "subject": {
            "id": subject.id,
            "code": subject.code,
            "title": subject.title,
            "grade_type": subject.grade_type,
            "grade_scale": grade_scale(subject),
            **subject_teacher_payload(subject),
        },
        "students": [_student_out(row) for row in students],
        "days": _journal_days(lessons),
        "entries": [_entry_out(row) for row in entries],
        "permissions": {
            "can_edit": student_viewer is None and not period.is_locked,
            "can_manage_topics": (
                student_viewer is None
                and has_permission(db, me, "journal.topic.manage")
            ),
        },
        "access_scope": "self" if student_viewer is not None else "group",
        "period": {"id": period.id, "is_locked": period.is_locked},
    }


@router.post("/lessons", status_code=201)
def create_journal_lesson(
    payload: JournalLessonCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    ensure_permission(db, me, "journal.lesson.write")
    if idempotency_key and len(idempotency_key) > 255:
        error(
            400,
            "JOURNAL_INVALID_IDEMPOTENCY_KEY",
            "Idempotency-Key не должен превышать 255 символов",
        )
    if idempotency_key:
        existing = db.scalar(
            select(JournalLesson)
            .options(joinedload(JournalLesson.topic), joinedload(JournalLesson.period))
            .where(JournalLesson.idempotency_key == idempotency_key)
        )
        if existing:
            ensure_lesson_access(db, me, existing)
            return _lesson_out(existing)

    group = db.get(Group, payload.group_id)
    subject = db.get(Subject, payload.subject_id)
    if not group or not subject:
        error(404, "JOURNAL_NOT_FOUND", "Группа или дисциплина не найдена")
    period = period_for_date(db, payload.date)
    ensure_unlocked(period)
    current_teacher = ensure_pair_access(
        db,
        me,
        payload.group_id,
        payload.subject_id,
        period.academic_year,
        period.semester,
    )
    if current_teacher:
        if payload.teacher_id and payload.teacher_id != current_teacher.id:
            error(403, "JOURNAL_ACCESS_DENIED", "Нельзя создать занятие от другого преподавателя")
        teacher = current_teacher
    else:
        assigned_teacher_ids = list(
            dict.fromkeys(
                db.scalars(
                    select(JournalAssignment.teacher_id).where(
                        JournalAssignment.group_id == payload.group_id,
                        JournalAssignment.subject_id == payload.subject_id,
                        JournalAssignment.academic_year == period.academic_year,
                        JournalAssignment.semester == period.semester,
                        JournalAssignment.is_active.is_(True),
                    )
                ).all()
            )
        )
        if payload.teacher_id is not None:
            if payload.teacher_id not in assigned_teacher_ids:
                error(
                    422,
                    "JOURNAL_TEACHER_NOT_ASSIGNED",
                    "Преподаватель не назначен на журнал группы по этой дисциплине",
                )
            teacher = db.get(Teacher, payload.teacher_id)
        elif len(assigned_teacher_ids) == 1:
            teacher = db.get(Teacher, assigned_teacher_ids[0])
        elif not assigned_teacher_ids:
            error(
                422,
                "JOURNAL_ASSIGNMENT_REQUIRED",
                "Сначала назначьте преподавателя на журнал группы по дисциплине",
            )
        else:
            error(
                422,
                "JOURNAL_TEACHER_REQUIRED",
                "У журнала несколько преподавателей; укажите, кто проводит занятие",
                {"teacher_ids": assigned_teacher_ids},
            )

    lesson_type = payload.type or "practice"
    if payload.schedule_lesson_id is not None:
        schedule_lesson = db.get(Lesson, payload.schedule_lesson_id)
        if not schedule_lesson:
            error(404, "JOURNAL_SCHEDULE_LESSON_NOT_FOUND", "Занятие расписания не найдено")
        if (
            schedule_lesson.group_id != payload.group_id
            or schedule_lesson.subject_id != payload.subject_id
        ):
            error(
                422,
                "JOURNAL_SCHEDULE_LESSON_MISMATCH",
                "Занятие расписания относится к другой группе или дисциплине",
            )
        linked_lesson_id = db.scalar(
            select(JournalLesson.id).where(
                JournalLesson.schedule_lesson_id == payload.schedule_lesson_id
            )
        )
        if linked_lesson_id:
            error(
                409,
                "JOURNAL_LESSON_DUPLICATE",
                "Занятие расписания уже добавлено в журнал",
                {"journal_lesson_id": linked_lesson_id},
            )
        if schedule_lesson.subject_type is None:
            lesson_type = "practice"
        elif schedule_lesson.subject_type in {
            "lecture",
            "practice",
            "educational_practice",
        }:
            lesson_type = schedule_lesson.subject_type
        else:
            error(
                422,
                "JOURNAL_INVALID_LESSON_TYPE",
                "Тип занятия расписания не поддерживается",
                {"type": schedule_lesson.subject_type},
            )

    if not teacher_is_linked_to_subject(db, teacher.id, subject.id):
        error(
            422,
            "JOURNAL_TEACHER_NOT_LINKED",
            "Преподаватель не связан с выбранной дисциплиной",
            {"teacher_id": teacher.id, "subject_id": subject.id},
        )

    topic = None
    if payload.topic_id:
        topic = db.get(SubjectTopic, payload.topic_id)
        if not topic or topic.subject_id != subject.id or not topic.is_active:
            error(422, "JOURNAL_TOPIC_SUBJECT_MISMATCH", "Тема не принадлежит дисциплине")
    topic_text = payload.topic_text or (topic.title if topic else "")

    lesson = JournalLesson(
        group_id=payload.group_id,
        subject_id=payload.subject_id,
        teacher_id=teacher.id,
        period_id=period.id,
        lesson_date=payload.date,
        hours=payload.hours,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        lesson_type=lesson_type,
        topic_id=topic.id if topic else None,
        topic_text=topic_text,
        comment=payload.comment,
        schedule_lesson_id=payload.schedule_lesson_id,
        status=payload.status,
        idempotency_key=idempotency_key,
        created_by=me.id,
        updated_by=me.id,
    )
    db.add(lesson)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return _lesson_create_conflict(
            db, me, idempotency_key, payload.schedule_lesson_id
        )

    students = db.scalars(
        select(Student).options(joinedload(Student.user)).where(Student.group_id == group.id)
    ).unique().all()
    for student in students:
        db.add(
            JournalLessonStudent(
                lesson_id=lesson.id,
                student_id=student.id,
                full_name=student_full_name(student),
                record_book=student.record_book,
            )
        )
    add_audit(
        db,
        me,
        "lesson",
        lesson.id,
        "create",
        None,
        lesson_state(lesson),
        lesson_id=lesson.id,
        request_id=_request_id(request_id),
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _lesson_create_conflict(
            db, me, idempotency_key, payload.schedule_lesson_id
        )
    db.refresh(lesson)
    if topic:
        lesson.topic = topic
    return _lesson_out(lesson)


@router.patch("/lessons/{lesson_id}")
def patch_journal_lesson(
    lesson_id: int,
    payload: JournalLessonPatch,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    ensure_permission(db, me, "journal.lesson.write")
    lesson = db.scalar(
        select(JournalLesson)
        .options(joinedload(JournalLesson.period), joinedload(JournalLesson.topic))
        .where(JournalLesson.id == lesson_id)
    )
    if not lesson:
        error(404, "JOURNAL_LESSON_NOT_FOUND", "Занятие не найдено")
    ensure_lesson_access(db, me, lesson)
    ensure_unlocked(lesson.period)
    if payload.version != lesson.version:
        error(
            409,
            "JOURNAL_VERSION_CONFLICT",
            "Занятие уже изменено",
            {"current": _lesson_out(lesson)},
        )

    before = lesson_state(lesson)
    changes = payload.model_fields_set - {"version"}
    if "date" in changes and payload.date is not None:
        target_period = period_for_date(db, payload.date)
        ensure_unlocked(target_period)
        ensure_pair_access(
            db,
            me,
            lesson.group_id,
            lesson.subject_id,
            target_period.academic_year,
            target_period.semester,
        )
        lesson.lesson_date = payload.date
        lesson.period_id = target_period.id
        lesson.period = target_period
    for field, attr in (
        ("hours", "hours"),
        ("starts_at", "starts_at"),
        ("ends_at", "ends_at"),
        ("type", "lesson_type"),
        ("comment", "comment"),
        ("status", "status"),
    ):
        if field in changes:
            setattr(lesson, attr, getattr(payload, field))

    if lesson.starts_at and lesson.ends_at and lesson.ends_at <= lesson.starts_at:
        error(422, "JOURNAL_INVALID_TIME_RANGE", "ends_at должен быть позже starts_at")
    if "topic_id" in changes:
        if payload.topic_id is None:
            lesson.topic_id = None
            lesson.topic = None
        else:
            topic = db.get(SubjectTopic, payload.topic_id)
            if not topic or topic.subject_id != lesson.subject_id or not topic.is_active:
                error(422, "JOURNAL_TOPIC_SUBJECT_MISMATCH", "Тема не принадлежит дисциплине")
            lesson.topic_id = topic.id
            lesson.topic = topic
            if "topic_text" not in changes:
                lesson.topic_text = topic.title
    if "topic_text" in changes:
        lesson.topic_text = payload.topic_text or ""
    if not lesson.topic_text.strip():
        error(422, "JOURNAL_TOPIC_REQUIRED", "Укажите тему занятия")

    lesson.version += 1
    lesson.updated_by = me.id
    add_audit(
        db,
        me,
        "lesson",
        lesson.id,
        "update",
        before,
        lesson_state(lesson),
        lesson_id=lesson.id,
        request_id=_request_id(request_id),
    )
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        error(409, "JOURNAL_VERSION_CONFLICT", "Занятие уже изменено")
    except IntegrityError:
        db.rollback()
        error(409, "JOURNAL_LESSON_CONFLICT", "Не удалось изменить занятие")
    db.refresh(lesson)
    return _lesson_out(lesson)


@router.delete("/lessons/{lesson_id}", status_code=204)
def cancel_journal_lesson(
    lesson_id: int,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    ensure_permission(db, me, "journal.lesson.write")
    lesson = db.scalar(
        select(JournalLesson)
        .options(joinedload(JournalLesson.period))
        .where(JournalLesson.id == lesson_id)
    )
    if not lesson:
        error(404, "JOURNAL_LESSON_NOT_FOUND", "Занятие не найдено")
    ensure_lesson_access(db, me, lesson)
    ensure_unlocked(lesson.period)
    if lesson.status != "cancelled":
        before = lesson_state(lesson)
        lesson.status = "cancelled"
        lesson.version += 1
        lesson.updated_by = me.id
        add_audit(
            db,
            me,
            "lesson",
            lesson.id,
            "cancel",
            before,
            lesson_state(lesson),
            lesson_id=lesson.id,
            request_id=_request_id(request_id),
        )
        db.commit()
    return Response(status_code=204)


def _save_entry(
    db: Session,
    me: User,
    lesson: JournalLesson,
    student_id: int,
    payload: JournalEntryPut,
    request_id: str | None,
) -> JournalEntry:
    snapshot_exists = db.scalar(
        select(JournalLessonStudent.id).where(
            JournalLessonStudent.lesson_id == lesson.id,
            JournalLessonStudent.student_id == student_id,
        )
    )
    if not snapshot_exists:
        error(422, "JOURNAL_STUDENT_NOT_IN_LESSON", "Студент не входит в состав занятия")
    validate_grade(lesson.subject, payload.grade)
    entry = db.scalar(
        select(JournalEntry).where(
            JournalEntry.lesson_id == lesson.id,
            JournalEntry.student_id == student_id,
        )
    )
    if entry:
        if payload.version != entry.version:
            error(
                409,
                "JOURNAL_VERSION_CONFLICT",
                "Запись уже изменена",
                {"current": _entry_out(entry)},
            )
        before = entry_state(entry)
        entry.attendance = payload.attendance
        entry.grade = payload.grade
        entry.comment = payload.comment
        entry.version += 1
        operation = "update"
    else:
        if payload.version not in {0, 1}:
            error(409, "JOURNAL_VERSION_CONFLICT", "Запись ещё не существует")
        before = None
        entry = JournalEntry(
            lesson_id=lesson.id,
            student_id=student_id,
            attendance=payload.attendance,
            grade=payload.grade,
            comment=payload.comment,
            version=1,
            updated_by=me.id,
        )
        db.add(entry)
        db.flush()
        operation = "create"
    entry.updated_by = me.id
    add_audit(
        db,
        me,
        "entry",
        entry.id,
        operation,
        before,
        entry_state(entry),
        lesson_id=lesson.id,
        student_id=student_id,
        request_id=_request_id(request_id),
    )
    return entry


def _entry_lesson(db: Session, me: User, lesson_id: int) -> JournalLesson:
    ensure_permission(db, me, "journal.entry.write")
    lesson = db.scalar(
        select(JournalLesson)
        .options(joinedload(JournalLesson.period), joinedload(JournalLesson.subject))
        .where(JournalLesson.id == lesson_id)
    )
    if not lesson:
        error(404, "JOURNAL_LESSON_NOT_FOUND", "Занятие не найдено")
    ensure_lesson_access(db, me, lesson)
    ensure_unlocked(lesson.period)
    if lesson.status == "cancelled":
        error(422, "JOURNAL_LESSON_CANCELLED", "Отменённое занятие нельзя редактировать")
    return lesson


@router.put("/lessons/{lesson_id}/entries/{student_id}")
def put_journal_entry(
    lesson_id: int,
    student_id: int,
    payload: JournalEntryPut,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    lesson = _entry_lesson(db, me, lesson_id)
    entry = _save_entry(db, me, lesson, student_id, payload, request_id)
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        error(409, "JOURNAL_VERSION_CONFLICT", "Запись уже изменена")
    except IntegrityError:
        db.rollback()
        error(409, "JOURNAL_ENTRY_DUPLICATE", "Запись уже создана другим пользователем")
    db.refresh(entry)
    return _entry_out(entry)


@router.put("/lessons/{lesson_id}/entries:batch")
def put_journal_entries_batch(
    lesson_id: int,
    payload: JournalBatchPut,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    lesson = _entry_lesson(db, me, lesson_id)
    seen: set[int] = set()
    updated: list[JournalEntry] = []
    failed: list[dict] = []
    for item in payload.entries:
        if item.student_id in seen:
            failed.append(
                {
                    "student_id": item.student_id,
                    "code": "JOURNAL_DUPLICATE_STUDENT",
                    "message": "Студент повторяется в batch-запросе",
                }
            )
            continue
        seen.add(item.student_id)
        try:
            with db.begin_nested():
                entry = _save_entry(db, me, lesson, item.student_id, item, request_id)
                db.flush()
            updated.append(entry)
        except (JournalAPIError, StaleDataError, IntegrityError) as exc:
            if isinstance(exc, JournalAPIError):
                data = exc.detail["error"]
            elif isinstance(exc, StaleDataError):
                data = {"code": "JOURNAL_VERSION_CONFLICT", "message": "Запись уже изменена"}
            else:
                data = {"code": "JOURNAL_ENTRY_DUPLICATE", "message": "Запись уже создана"}
            failed.append(
                {
                    "student_id": item.student_id,
                    "code": data["code"],
                    "message": data["message"],
                }
            )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        error(409, "JOURNAL_BATCH_CONFLICT", "Не удалось сохранить пакет записей")
    return {"updated": [_entry_out(row) for row in updated], "failed": failed}
