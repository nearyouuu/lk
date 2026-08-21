import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.core.deps import get_db, get_current_user, require_role_any, require_feature
from app.core.config import settings
from app.models.user import User
from app.models.grade import Student as StudentModel
from app.models.application import Application
from app.schemas.application import ApplicationCreate, ApplicationOut, ApplicationUpdate

router = APIRouter(
    prefix="/applications",
    tags=["applications"],
    dependencies=[Depends(require_feature("applications"))],
)

def save_file(student_id: int, file: UploadFile) -> str:
    """Сохраняет прикреплённый файл"""
    ext = os.path.splitext(file.filename or "")[1] or ".bin"
    fname = f"{student_id}_{uuid.uuid4().hex}{ext}"
    rel_dir = os.path.join("applications", str(student_id))
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    abs_path = os.path.join(abs_dir, fname)
    with open(abs_path, "wb") as f:
        f.write(file.file.read())
    return os.path.join(rel_dir, fname).replace("\\", "/")

@router.post("/", response_model=ApplicationOut, dependencies=[Depends(require_role_any(["student"]))])
async def create_application(
    title: str = Form(...),
    text: str = Form(...),
    type: str = Form("certificate"),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """📨 Подать заявление / заказать справку"""
    student = db.scalar(select(StudentModel).where(StudentModel.user_id == user.id))
    if not student:
        raise HTTPException(403, "Только студенты могут подавать заявления")

    file_path = save_file(student.id, file) if file else None

    app = Application(
        student_id=student.id,
        title=title.strip(),
        text=text.strip(),
        type=type,
        file_path=file_path,
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    return app


@router.get("/my", response_model=list[ApplicationOut], dependencies=[Depends(require_role_any(["student"]))])
async def my_applications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """📋 Мои поданные заявления"""
    student = db.scalar(select(StudentModel).where(StudentModel.user_id == user.id))
    if not student:
        raise HTTPException(403, "Только студенты могут просматривать свои заявления")

    items = db.scalars(
        select(Application).where(Application.student_id == student.id).order_by(Application.created_at.desc())
    ).all()
    return items


@router.get("/all", response_model=list[ApplicationOut],
            dependencies=[Depends(require_role_any(["administrator", "director"]))])
async def list_all_applications(
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
):
    """🧾 Все заявления (для администрации)"""
    stmt = select(Application)
    if status:
        stmt = stmt.where(Application.status == status)
    if type:
        stmt = stmt.where(Application.type == type)
    items = db.scalars(stmt.order_by(Application.created_at.desc())).all()
    return items


@router.post("/{application_id}", response_model=ApplicationOut,
              dependencies=[Depends(require_role_any(["administrator", "director"]))])
async def update_application_status(
    application_id: int,
    data: ApplicationUpdate,
    db: Session = Depends(get_db),
):
    """✏️ Изменить статус и комментарий по заявлению"""
    app = db.get(Application, application_id)
    if not app:
        raise HTTPException(404, "Application not found")

    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(app, k, v)
    db.commit()
    db.refresh(app)
    return app
