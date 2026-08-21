import os
import uuid
from typing import Optional

from fastapi import (
    APIRouter, Depends, HTTPException, UploadFile,
    File, Form, Query
)
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.core.deps import (
    get_db,
    get_current_user,
    require_role_any,
    require_feature,
)
from app.core.config import settings
from app.models.user import User
from app.models.grade import Student as StudentModel
from app.models.schedule import Subject, Group, Teacher
from app.models.material import Material
from app.schemas.material import MaterialOut, MaterialUpdate
from app.services.subject_service import resolve_subject

router = APIRouter(
    prefix="/materials",
    tags=["materials"],
    dependencies=[Depends(require_feature("materials"))],
)

def ensure_dir(path: str):
    """Создаёт директорию, если её нет."""
    os.makedirs(path, exist_ok=True)


def build_rel_path(*parts: str) -> str:
    """Формирует относительный путь для хранения в БД."""
    return "/".join(str(p).strip("/\\") for p in parts if p)


def save_uploaded_file(subject_id: int, group_id: int, file: UploadFile) -> str:
    """Сохраняет файл в media/materials/{subject_id}/{group_id}/ и возвращает относительный путь."""
    ext = os.path.splitext(file.filename or "")[1] or ".bin"
    fname = f"{uuid.uuid4().hex}{ext}"

    rel_dir = build_rel_path("materials", str(subject_id), str(group_id))
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    ensure_dir(abs_dir)

    abs_path = os.path.join(abs_dir, fname)
    with open(abs_path, "wb") as f:
        f.write(file.file.read())

    return build_rel_path(rel_dir, fname)


def assert_subject_group(db: Session, subject_id: int, group_id: int):
    """Проверка, что предмет и группа существуют."""
    if not db.get(Subject, subject_id):
        raise HTTPException(400, "Subject not found")
    if not db.get(Group, group_id):
        raise HTTPException(400, "Group not found")


def get_teacher_by_user(db: Session, user: User) -> Teacher:
    """Возвращает объект Teacher по user_id."""
    teacher = db.scalar(select(Teacher).where(Teacher.user_id == user.id))
    if not teacher:
        raise HTTPException(403, "Only teachers can manage materials")
    return teacher

@router.post(
    "/",
    response_model=MaterialOut,
    dependencies=[Depends(require_role_any(["teacher", "administrator", "director"]))],
)
async def create_material(
    group_id: int = Form(...),
    title: str = Form(...),
    subject_code: Optional[str] = Form(None),
    subject_id: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    type: str = Form("document"),
    link: Optional[str] = Form(None),
    text_content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    ➕ Добавить новый учебный материал.
    Можно загрузить файл или указать ссылку (например, на видео/документ).
    """
    subject = resolve_subject(db, subject_code, subject_id, status_code=400)
    assert_subject_group(db, subject.id, group_id)
    teacher = get_teacher_by_user(db, user)

    file_path = save_uploaded_file(subject.id, group_id, file) if file else None

    material = Material(
        title=title.strip(),
        description=description or None,
        type=type,
        subject_id=subject.id,
        group_id=group_id,
        teacher_id=teacher.id,
        link=link or None,
        text_content=text_content or None,
        file_path=file_path,
        is_published=True,
    )

    db.add(material)
    db.commit()
    db.refresh(material)
    return material


@router.post(
    "/{material_id}/patch",
    response_model=MaterialOut,
    dependencies=[Depends(require_role_any(["teacher", "administrator", "director"]))],
)
async def update_material(
    material_id: int,
    payload: MaterialUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """✏️ Изменить существующий материал."""
    mat = db.get(Material, material_id)
    if not mat:
        raise HTTPException(404, "Material not found")

    teacher = db.scalar(select(Teacher).where(Teacher.user_id == user.id))
    if teacher and mat.teacher_id != teacher.id:
        raise HTTPException(403, "You cannot edit materials of other teachers")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(mat, field, value)

    db.commit()
    db.refresh(mat)
    return mat


@router.post(
    "/{material_id}/file",
    response_model=MaterialOut,
    dependencies=[Depends(require_role_any(["teacher", "administrator", "director"]))],
)
async def upload_file(
    material_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """📤 Заменить или добавить файл к материалу."""
    mat = db.get(Material, material_id)
    if not mat:
        raise HTTPException(404, "Material not found")

    teacher = db.scalar(select(Teacher).where(Teacher.user_id == user.id))
    if teacher and mat.teacher_id != teacher.id:
        raise HTTPException(403, "You cannot modify other teachers' materials")

    if mat.file_path:
        old_abs = os.path.join(settings.MEDIA_ROOT, mat.file_path)
        if os.path.exists(old_abs):
            try:
                os.remove(old_abs)
            except Exception:
                pass

    mat.file_path = save_uploaded_file(mat.subject_id, mat.group_id, file)
    db.commit()
    db.refresh(mat)
    return mat


@router.post(
    "/{material_id}/delete",
    dependencies=[Depends(require_role_any(["teacher", "administrator", "director"]))],
)
async def delete_material(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """🗑️ Удалить материал."""
    mat = db.get(Material, material_id)
    if not mat:
        raise HTTPException(404, "Material not found")

    teacher = db.scalar(select(Teacher).where(Teacher.user_id == user.id))
    if teacher and mat.teacher_id != teacher.id:
        raise HTTPException(403, "You cannot delete others' materials")

    if mat.file_path:
        abs_path = os.path.join(settings.MEDIA_ROOT, mat.file_path)
        if os.path.exists(abs_path):
            try:
                os.remove(abs_path)
            except Exception:
                pass

    db.delete(mat)
    db.commit()
    return {"status": "deleted"}

@router.get("/my", response_model=list[MaterialOut])
async def get_my_materials(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    subject_code: Optional[str] = Query(None),
    subject_id: Optional[int] = Query(None),
):
    """📚 Список материалов для текущего студента."""
    student = db.scalar(select(StudentModel).where(StudentModel.user_id == user.id))
    if not student:
        raise HTTPException(403, "Only students can access this endpoint")

    stmt = select(Material).where(
        Material.group_id == student.group_id,
        Material.is_published.is_(True)
    )
    if subject_code or subject_id is not None:
        subject = resolve_subject(db, subject_code, subject_id, status_code=400)
        stmt = stmt.where(Material.subject_id == subject.id)

    materials = db.scalars(stmt.order_by(Material.created_at.desc())).all()
    return materials

@router.get("/by_group_subject", response_model=list[MaterialOut])
async def get_materials_by_group_subject(
    group_id: int = Query(...),
    subject_code: Optional[str] = Query(None),
    subject_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """🔎 Материалы для конкретной группы и предмета."""
    subject = resolve_subject(db, subject_code, subject_id, status_code=400)
    assert_subject_group(db, subject.id, group_id)
    stmt = select(Material).where(
        Material.group_id == group_id,
        Material.subject_id == subject.id,
        Material.is_published.is_(True)
    )
    items = db.scalars(stmt.order_by(Material.created_at.desc())).all()
    return items

@router.get(
    "/all",
    response_model=list[MaterialOut],
    dependencies=[Depends(require_role_any(["administrator", "director"]))],
)
async def get_all_materials(
    db: Session = Depends(get_db),
    subject_code: Optional[str] = Query(None),
    subject_id: Optional[int] = Query(None),
    group_id: Optional[int] = Query(None),
    teacher_id: Optional[int] = Query(None),
):
    """📋 Полный список всех материалов (фильтруется по предмету, группе, преподавателю)."""
    stmt = select(Material)
    if subject_code or subject_id is not None:
        subject = resolve_subject(db, subject_code, subject_id, status_code=400)
        stmt = stmt.where(Material.subject_id == subject.id)
    if group_id:
        stmt = stmt.where(Material.group_id == group_id)
    if teacher_id:
        stmt = stmt.where(Material.teacher_id == teacher_id)

    items = db.scalars(stmt.order_by(Material.created_at.desc())).all()
    return items
