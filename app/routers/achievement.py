import os
import uuid
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Security
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.core.deps import get_db, require_permission, get_current_user, require_feature
from app.models.achievement import Achievement, AchievementStatus, AchievementType
from app.schemas.achievement import AchievementOut
from app.models.user import User
from typing import Optional, List

MEDIA_DIR = "media/achievements"
os.makedirs(MEDIA_DIR, exist_ok=True)

router = APIRouter(
    prefix="/achievements",
    tags=["achievements"],
    dependencies=[Depends(require_feature("portfolio"))],
)


def save_file(student_id: int, file: UploadFile) -> str:
    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{student_id}_{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(MEDIA_DIR, unique_name)
    with open(filepath, "wb") as buffer:
        buffer.write(file.file.read())
    return filepath


def delete_file(path: str):
    if path and os.path.exists(path):
        os.remove(path)

@router.post("", response_model=AchievementOut)
async def create_achievement(
    student_id: int = Form(...),
    name: str = Form(...),
    description: str = Form(...),
    type: AchievementType = Form(AchievementType.academic),
    status: AchievementStatus = Form(AchievementStatus.pending),
    event_date: Optional[date] = Form(None),
    points: int = Form(0),
    approved_by: Optional[str] = Form(None),
    admin_message: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    image_path = None
    if image:
        image_path = save_file(student_id, image)

    ach = Achievement(
        student_id=student_id,
        name=name or "Без названия",
        description=description,
        status=status,
        admin_message=admin_message,
        image_path=image_path,
        type=type,
        event_date=event_date,
        points=points,
        approved_by=approved_by,
    )
    db.add(ach)
    db.commit()
    db.refresh(ach)
    return ach

@router.get("", response_model=List[AchievementOut], dependencies=[Depends(require_permission("achievements:read"))])
def list_achievements(
    db: Session = Depends(get_db),
    type: Optional[AchievementType] = Query(None),
    status: Optional[AchievementStatus] = Query(None),
):
    query = select(Achievement)
    if type:
        query = query.where(Achievement.type == type)
    if status:
        query = query.where(Achievement.status == status)
    query = query.order_by(Achievement.created_at.desc())
    return db.scalars(query).all()


@router.get("/student/{student_id}", response_model=List[AchievementOut])
def list_student_achievements(student_id: int, db: Session = Depends(get_db)):
    return db.scalars(
        select(Achievement)
        .where(Achievement.student_id == student_id)
        .order_by(Achievement.created_at.desc())
    ).all()


@router.get("/{achievement_id}", response_model=AchievementOut)
def get_achievement(achievement_id: int, db: Session = Depends(get_db)):
    ach = db.get(Achievement, achievement_id)
    if not ach:
        raise HTTPException(status_code=404, detail="Achievement not found")
    return ach


@router.post("/{achievement_id}/patch", response_model=AchievementOut, dependencies=[Depends(require_permission("achievements:update"))])
async def update_achievement(
    achievement_id: int,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    status: Optional[AchievementStatus] = Form(None),
    admin_message: Optional[str] = Form(None),
    type: Optional[AchievementType] = Form(None),
    event_date: Optional[date] = Form(None),
    points: Optional[int] = Form(None),
    approved_by: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    ach = db.get(Achievement, achievement_id)
    if not ach:
        raise HTTPException(status_code=404, detail="Achievement not found")

    if name is not None:
        ach.name = name
    if description is not None:
        ach.description = description
    if status is not None:
        ach.status = status
    if admin_message is not None:
        ach.admin_message = admin_message
    if type is not None:
        ach.type = type
    if event_date is not None:
        ach.event_date = event_date
    if points is not None:
        ach.points = points
    if approved_by is not None:
        ach.approved_by = approved_by

    if image:
        delete_file(ach.image_path)
        ach.image_path = save_file(ach.student_id, image)

    db.commit()
    db.refresh(ach)
    return ach


@router.post("/student/{student_id}/{achievement_id}")
def delete_student_achievement(
    student_id: int,
    achievement_id: int,
    db: Session = Depends(get_db),
):
    ach = db.scalar(
        select(Achievement).where(
            Achievement.id == achievement_id,
            Achievement.student_id == student_id,
        )
    )
    if not ach:
        raise HTTPException(status_code=404, detail="Achievement not found")

    delete_file(ach.image_path)
    db.delete(ach)
    db.commit()
    return {"ok": True}


@router.post("/{achievement_id}/delete", dependencies=[Depends(require_permission("achievements:delete"))])
def admin_delete_achievement(
    achievement_id: int,
    db: Session = Depends(get_db),
):
    ach = db.get(Achievement, achievement_id)
    if not ach:
        raise HTTPException(status_code=404, detail="Achievement not found")

    delete_file(ach.image_path)
    db.delete(ach)
    db.commit()
    return {"ok": True}
