from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user, get_db
from app.models.journal import (
    JournalAssignment,
    JournalAuditEvent,
    JournalPeriod,
    SubjectTopic,
)
from app.models.schedule import Group, Subject, Teacher
from app.models.user import User
from app.schemas.journal import (
    JournalAssignmentCreate,
    SubjectTopicCreate,
    SubjectTopicPatch,
    SubjectTopicsReorder,
)
from app.services.journal_service import (
    error,
    get_or_create_period,
    has_permission,
    is_privileged,
)


router = APIRouter(prefix="/api/v1/admin", tags=["journal-admin"])


def _require_topics(db: Session, me: User):
    if not has_permission(db, me, "journal.topic.manage"):
        error(403, "JOURNAL_ACCESS_DENIED", "Нет права на управление темами")


def _require_privileged(db: Session, me: User):
    if not is_privileged(db, me):
        error(403, "JOURNAL_ACCESS_DENIED", "Операция доступна администратору или директору")


def _topic_out(topic: SubjectTopic) -> dict:
    return {
        "id": topic.id,
        "subject_id": topic.subject_id,
        "title": topic.title,
        "description": topic.description,
        "sort_order": topic.sort_order,
        "is_active": topic.is_active,
    }


@router.get("/subjects/{subject_id}/topics")
def list_subject_topics(
    subject_id: int,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if not (
        has_permission(db, me, "journal.read")
        or has_permission(db, me, "journal.topic.manage")
    ):
        error(403, "JOURNAL_ACCESS_DENIED", "Нет права на просмотр тем")
    if not db.get(Subject, subject_id):
        error(404, "JOURNAL_SUBJECT_NOT_FOUND", "Дисциплина не найдена")
    query = select(SubjectTopic).where(SubjectTopic.subject_id == subject_id)
    if not include_inactive:
        query = query.where(SubjectTopic.is_active.is_(True))
    topics = db.scalars(query.order_by(SubjectTopic.sort_order, SubjectTopic.id)).all()
    return {"items": [_topic_out(row) for row in topics]}


@router.post("/subjects/{subject_id}/topics", status_code=201)
def create_subject_topic(
    subject_id: int,
    payload: SubjectTopicCreate,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _require_topics(db, me)
    if not db.get(Subject, subject_id):
        error(404, "JOURNAL_SUBJECT_NOT_FOUND", "Дисциплина не найдена")
    topic = SubjectTopic(
        subject_id=subject_id,
        title=payload.title,
        description=payload.description,
        sort_order=payload.sort_order,
        created_by=me.id,
        updated_by=me.id,
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return _topic_out(topic)


@router.patch("/subjects/{subject_id}/topics/{topic_id}")
def patch_subject_topic(
    subject_id: int,
    topic_id: int,
    payload: SubjectTopicPatch,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _require_topics(db, me)
    topic = db.get(SubjectTopic, topic_id)
    if not topic or topic.subject_id != subject_id:
        error(404, "JOURNAL_TOPIC_NOT_FOUND", "Тема не найдена")
    for field in payload.model_fields_set:
        setattr(topic, field, getattr(payload, field))
    topic.updated_by = me.id
    db.commit()
    db.refresh(topic)
    return _topic_out(topic)


@router.delete("/subjects/{subject_id}/topics/{topic_id}", status_code=204)
def delete_subject_topic(
    subject_id: int,
    topic_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _require_topics(db, me)
    topic = db.get(SubjectTopic, topic_id)
    if not topic or topic.subject_id != subject_id:
        error(404, "JOURNAL_TOPIC_NOT_FOUND", "Тема не найдена")
    topic.is_active = False
    topic.updated_by = me.id
    db.commit()
    return Response(status_code=204)


@router.put("/subjects/{subject_id}/topics:reorder")
def reorder_subject_topics(
    subject_id: int,
    payload: SubjectTopicsReorder,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _require_topics(db, me)
    if len(payload.topic_ids) != len(set(payload.topic_ids)):
        error(422, "JOURNAL_TOPIC_DUPLICATE", "topic_ids содержит повторения")
    topics = db.scalars(
        select(SubjectTopic).where(SubjectTopic.id.in_(payload.topic_ids))
    ).all()
    if len(topics) != len(payload.topic_ids) or any(
        row.subject_id != subject_id for row in topics
    ):
        error(422, "JOURNAL_TOPIC_SUBJECT_MISMATCH", "Все темы должны принадлежать дисциплине")
    by_id = {row.id: row for row in topics}
    for sort_order, topic_id in enumerate(payload.topic_ids):
        by_id[topic_id].sort_order = sort_order
        by_id[topic_id].updated_by = me.id
    db.commit()
    return {"items": [_topic_out(by_id[row_id]) for row_id in payload.topic_ids]}


@router.get("/journal/assignments")
def list_journal_assignments(
    academic_year: int | None = None,
    semester: str | None = None,
    teacher_id: int | None = None,
    group_id: int | None = None,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _require_privileged(db, me)
    query = select(JournalAssignment).options(
        joinedload(JournalAssignment.teacher),
        joinedload(JournalAssignment.group),
        joinedload(JournalAssignment.subject),
    )
    for column, value in (
        (JournalAssignment.academic_year, academic_year),
        (JournalAssignment.semester, semester),
        (JournalAssignment.teacher_id, teacher_id),
        (JournalAssignment.group_id, group_id),
    ):
        if value is not None:
            query = query.where(column == value)
    rows = db.scalars(query.order_by(JournalAssignment.id)).unique().all()
    return {"items": [_assignment_out(row) for row in rows]}


def _assignment_out(row: JournalAssignment) -> dict:
    return {
        "id": row.id,
        "teacher": {"id": row.teacher.id, "full_name": row.teacher.full_name},
        "group": {"id": row.group.id, "code": row.group.code},
        "subject": {"id": row.subject.id, "code": row.subject.code, "title": row.subject.title},
        "academic_year": row.academic_year,
        "semester": row.semester,
        "is_active": row.is_active,
    }


@router.post("/journal/assignments", status_code=201)
def create_journal_assignment(
    payload: JournalAssignmentCreate,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _require_privileged(db, me)
    teacher = db.get(Teacher, payload.teacher_id)
    group = db.get(Group, payload.group_id)
    subject = db.get(Subject, payload.subject_id)
    if not teacher or not group or not subject:
        error(404, "JOURNAL_ASSIGNMENT_REFERENCE_NOT_FOUND", "Преподаватель, группа или дисциплина не найдены")
    assignment = db.scalar(
        select(JournalAssignment).where(
            JournalAssignment.teacher_id == payload.teacher_id,
            JournalAssignment.group_id == payload.group_id,
            JournalAssignment.subject_id == payload.subject_id,
            JournalAssignment.academic_year == payload.academic_year,
            JournalAssignment.semester == payload.semester,
        )
    )
    if assignment:
        assignment.is_active = True
    else:
        assignment = JournalAssignment(
            **payload.model_dump(), is_active=True, created_by=me.id
        )
        db.add(assignment)
    get_or_create_period(db, payload.academic_year, payload.semester)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        error(409, "JOURNAL_ASSIGNMENT_DUPLICATE", "Назначение уже существует")
    db.refresh(assignment)
    assignment.teacher = teacher
    assignment.group = group
    assignment.subject = subject
    return _assignment_out(assignment)


@router.delete("/journal/assignments/{assignment_id}", status_code=204)
def delete_journal_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _require_privileged(db, me)
    assignment = db.get(JournalAssignment, assignment_id)
    if not assignment:
        error(404, "JOURNAL_ASSIGNMENT_NOT_FOUND", "Назначение не найдено")
    assignment.is_active = False
    db.commit()
    return Response(status_code=204)


@router.post("/journal/periods/{period_id}/lock")
def lock_journal_period(
    period_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _require_privileged(db, me)
    period = db.get(JournalPeriod, period_id)
    if not period:
        error(404, "JOURNAL_PERIOD_NOT_FOUND", "Учебный период не найден")
    period.is_locked = True
    period.locked_at = datetime.now(timezone.utc)
    period.locked_by = me.id
    db.commit()
    return {"id": period.id, "is_locked": True}


@router.post("/journal/periods/{period_id}/unlock")
def unlock_journal_period(
    period_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _require_privileged(db, me)
    period = db.get(JournalPeriod, period_id)
    if not period:
        error(404, "JOURNAL_PERIOD_NOT_FOUND", "Учебный период не найден")
    period.is_locked = False
    period.locked_at = None
    period.locked_by = None
    db.commit()
    return {"id": period.id, "is_locked": False}


@router.get("/journal/audit")
def journal_audit(
    lesson_id: int | None = None,
    student_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if not has_permission(db, me, "journal.audit.read"):
        error(403, "JOURNAL_ACCESS_DENIED", "Нет права на просмотр аудита")
    filters = []
    if lesson_id is not None:
        filters.append(JournalAuditEvent.lesson_id == lesson_id)
    if student_id is not None:
        filters.append(JournalAuditEvent.student_id == student_id)
    total = db.scalar(select(func.count(JournalAuditEvent.id)).where(*filters)) or 0
    rows = db.scalars(
        select(JournalAuditEvent)
        .where(*filters)
        .order_by(JournalAuditEvent.created_at.desc(), JournalAuditEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "actor_id": row.actor_id,
                "timestamp": row.created_at,
                "entity": row.entity,
                "entity_id": row.entity_id,
                "operation": row.operation,
                "before": row.before,
                "after": row.after,
                "request_id": row.request_id,
            }
            for row in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }
