from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schedule import Subject


def get_subject_by_code(db: Session, subject_code: str, status_code: int = 404) -> Subject:
    normalized_code = subject_code.strip()
    subjects = db.scalars(
        select(Subject).where(Subject.code == normalized_code).order_by(Subject.id).limit(2)
    ).all()
    if not subjects:
        raise HTTPException(status_code=status_code, detail="Subject not found")
    if len(subjects) > 1:
        raise HTTPException(
            status_code=409,
            detail="Subject code is ambiguous; use subject_id or subject_identifier",
        )
    return subjects[0]


def get_subject_by_identifier(
    db: Session, subject_identifier: str, status_code: int = 404
) -> Subject:
    subject = db.scalar(
        select(Subject).where(Subject.identifier == subject_identifier.strip())
    )
    if not subject:
        raise HTTPException(status_code=status_code, detail="Subject not found")
    return subject


def resolve_subject(
    db: Session,
    subject_code: str | None = None,
    subject_id: int | None = None,
    status_code: int = 404,
    subject_identifier: str | None = None,
) -> Subject:
    if subject_id is not None:
        subject = db.get(Subject, subject_id)
        if not subject:
            raise HTTPException(status_code=status_code, detail="Subject not found")
        return subject
    if subject_identifier:
        return get_subject_by_identifier(db, subject_identifier, status_code=status_code)
    if subject_code:
        return get_subject_by_code(db, subject_code, status_code=status_code)
    raise HTTPException(status_code=status_code, detail="Subject not found")
