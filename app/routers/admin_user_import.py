import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.deps import get_db, require_role_any
from app.services.user_importer import import_users_from_excel

router = APIRouter(prefix="/admin/users/import", tags=["admin-users"])

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "static", "users_template.xlsx")
EXPORT_DIR = "exports"
MAX_UPLOAD_SIZE = 10 * 1024 * 1024


@router.get("/template")
def download_template():
    """Скачать Excel-шаблон импорта пользователей и учебных справочников."""
    if not os.path.exists(TEMPLATE_PATH):
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    return FileResponse(
        TEMPLATE_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        # ASCII filename keeps older proxies and frontend content-disposition
        # parsers from corrupting or discarding the download name.
        filename="excel_import_template.xlsx",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/")
async def import_users(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(require_role_any(["administrator", "director"])),
):
    """Импортировать пользователей и справочники, скачать построчный отчёт."""
    filename = file.filename or ""
    if not filename.lower().endswith((".xls", ".xlsx")):
        raise HTTPException(status_code=400, detail="Требуется файл .xls или .xlsx")

    content = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Размер файла превышает 10 МБ")
    if not content:
        raise HTTPException(status_code=400, detail="Загружен пустой файл")

    suffix = ".xls" if filename.lower().endswith(".xls") else ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = import_users_from_excel(db, tmp_path, EXPORT_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Не удалось выполнить импорт") from exc
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return FileResponse(
        result.report_path,
        filename="результат_импорта.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "X-Import-Created": str(result.created),
            "X-Import-Skipped": str(result.skipped),
            "X-Import-Failed": str(result.failed),
            "X-Import-Groups-Created": str(result.groups_created),
            "X-Import-Subdivisions-Created": str(result.subdivisions_created),
            "X-Import-Rooms-Created": str(result.rooms_created),
            "X-Import-Subjects-Created": str(result.subjects_created),
            "X-Import-Subject-Types-Created": str(result.subject_types_created),
        },
        background=BackgroundTask(os.remove, result.report_path),
    )
