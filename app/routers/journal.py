from datetime import date, datetime, time

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
)
from app.services.journal_service import (
    JournalAPIError,
    add_audit,
    ensure_lesson_access,
    ensure_pair_access,
    ensure_permission,
    ensure_unlocked,
    entry_state,
    error,
    get_or_create_period,
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
        "starts_at": lesson.starts_at.isoformat() if lesson.starts_at else None,
        "ends_at": lesson.ends_at.isoformat() if lesson.ends_at else None,
        "type": lesson.lesson_type,
        "topic": (
            {"id": lesson.topic.id, "title": lesson.topic.title} if lesson.topic else None
        ),
        "topic_text": lesson.topic_text,
        "comment": lesson.comment,
        "schedule_lesson_id": lesson.schedule_lesson_id,
        "status": lesson.status,
        "version": lesson.version,
    }


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


@router.get("/catalog")
def journal_catalog(
    academic_year: int,
    semester: str,
    teacher_id: int | None = None,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    ensure_permission(db, me, "journal.read")
    starts_on, ends_on = period_bounds(academic_year, semester)
    privileged = is_privileged(db, me)
    if teacher_id is not None and not privileged:
        error(403, "JOURNAL_ACCESS_DENIED", "teacher_id доступен только администратору")

    if privileged:
        selected_teacher_id = teacher_id
    else:
        selected_teacher_id = get_teacher(db, me).id

    assignment_query = (
        select(JournalAssignment)
        .options(
            joinedload(JournalAssignment.group),
            joinedload(JournalAssignment.subject),
        )
        .where(
            JournalAssignment.academic_year == academic_year,
            JournalAssignment.semester == semester,
            JournalAssignment.is_active.is_(True),
        )
    )
    if selected_teacher_id is not None:
        assignment_query = assignment_query.where(
            JournalAssignment.teacher_id == selected_teacher_id
        )
    assignments = db.scalars(assignment_query).unique().all()

    pairs: dict[tuple[int, int], tuple[Group, Subject]] = {
        (row.group_id, row.subject_id): (row.group, row.subject) for row in assignments
    }

    schedule_query = (
        select(Lesson)
        .options(joinedload(Lesson.group), joinedload(Lesson.subject))
        .where(
            Lesson.subject_id.is_not(None),
            Lesson.starts_at >= datetime.combine(starts_on, time.min),
            Lesson.starts_at <= datetime.combine(ends_on, time.max),
        )
    )
    if selected_teacher_id is not None:
        schedule_query = schedule_query.where(Lesson.teacher_id == selected_teacher_id)
    for lesson in db.scalars(schedule_query).unique().all():
        if lesson.subject:
            pairs[(lesson.group_id, lesson.subject_id)] = (lesson.group, lesson.subject)

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
            }
        )
    return {
        "academic_year": academic_year,
        "semester": semester,
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


@router.get("")
def get_journal(
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
    teacher = ensure_pair_access(
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
    if teacher:
        query = query.where(JournalLesson.teacher_id == teacher.id)
    lessons = db.scalars(query).unique().all()

    snapshot_ids = {
        row.student_id for lesson in lessons for row in lesson.student_snapshots
    }
    current_ids = set(
        db.scalars(select(Student.id).where(Student.group_id == group_id)).all()
    )
    student_ids = snapshot_ids | current_ids
    students = db.scalars(
        select(Student)
        .options(joinedload(Student.user))
        .where(Student.id.in_(student_ids) if student_ids else False)
    ).unique().all()
    students.sort(key=student_full_name)
    entries = [entry for lesson in lessons for entry in lesson.entries]

    return {
        "group": {"id": group.id, "code": group.code},
        "subject": {
            "id": subject.id,
            "code": subject.code,
            "title": subject.title,
            "grade_scale": grade_scale(subject),
        },
        "students": [_student_out(row) for row in students],
        "lessons": [_lesson_out(row) for row in lessons],
        "entries": [_entry_out(row) for row in entries],
        "permissions": {
            "can_edit": not period.is_locked,
            "can_manage_topics": has_permission(db, me, "journal.topic.manage"),
        },
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
        teacher = db.get(Teacher, payload.teacher_id) if payload.teacher_id else None
        if not teacher:
            teacher = db.scalar(
                select(Teacher)
                .join(JournalAssignment, JournalAssignment.teacher_id == Teacher.id)
                .where(
                    JournalAssignment.group_id == payload.group_id,
                    JournalAssignment.subject_id == payload.subject_id,
                    JournalAssignment.academic_year == period.academic_year,
                    JournalAssignment.semester == period.semester,
                    JournalAssignment.is_active.is_(True),
                )
                .limit(1)
            )
        if not teacher and subject.primary_teacher_id:
            teacher = db.get(Teacher, subject.primary_teacher_id)
        if not teacher:
            error(422, "JOURNAL_TEACHER_REQUIRED", "Для занятия не назначен преподаватель")

    topic = None
    if payload.topic_id:
        topic = db.get(SubjectTopic, payload.topic_id)
        if not topic or topic.subject_id != subject.id or not topic.is_active:
            error(422, "JOURNAL_TOPIC_SUBJECT_MISMATCH", "Тема не принадлежит дисциплине")
    topic_text = payload.topic_text or (topic.title if topic else None)
    if not topic_text:
        error(422, "JOURNAL_TOPIC_REQUIRED", "Тема занятия обязательна")

    duplicate_query = select(JournalLesson.id).where(
        JournalLesson.group_id == payload.group_id,
        JournalLesson.subject_id == payload.subject_id,
        JournalLesson.lesson_date == payload.date,
        JournalLesson.starts_at.is_(None)
        if payload.starts_at is None
        else JournalLesson.starts_at == payload.starts_at,
    )
    if db.scalar(duplicate_query):
        error(409, "JOURNAL_LESSON_DUPLICATE", "Занятие в это время уже существует")

    lesson = JournalLesson(
        group_id=payload.group_id,
        subject_id=payload.subject_id,
        teacher_id=teacher.id,
        period_id=period.id,
        lesson_date=payload.date,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        lesson_type=payload.type,
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
    db.flush()

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
    except IntegrityError as exc:
        db.rollback()
        error(409, "JOURNAL_LESSON_DUPLICATE", "Занятие уже существует")
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
        if not payload.topic_text:
            error(422, "JOURNAL_TOPIC_REQUIRED", "Тема занятия обязательна")
        lesson.topic_text = payload.topic_text

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
        error(409, "JOURNAL_LESSON_DUPLICATE", "Занятие в это время уже существует")
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
