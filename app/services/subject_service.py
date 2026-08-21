from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schedule import Subject


def get_subject_by_code(db: Session, subject_code: str, status_code: int = 404) -> Subject:
    normalized_code = subject_code.strip()
    subject = db.scalar(select(Subject).where(Subject.code == normalized_code))
    if not subject:
        raise HTTPException(status_code=status_code, detail="Subject not found")
    return subject


def resolve_subject(
    db: Session,
    subject_code: str | None = None,
    subject_id: int | None = None,
    status_code: int = 404,
) -> Subject:
    if subject_code:
        return get_subject_by_code(db, subject_code, status_code=status_code)
    subject = db.get(Subject, subject_id) if subject_id is not None else None
    if not subject:
        raise HTTPException(status_code=status_code, detail="Subject not found")
    return subject
