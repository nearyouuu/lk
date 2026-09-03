from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from app.core.deps import get_db, require_role_any
from app.services.schedule_importer import parse_schedule_excel
from app.models.schedule import LessonTime, Lesson
from sqlalchemy import select
from app.schemas.schedule import LessonCreate, LessonOut, LessonTimeCreate
from fastapi.responses import FileResponse
import os
from datetime import time
from app.services.lesson_service import create_lesson

router = APIRouter(prefix="/admin/schedule", tags=["admin-schedule"])

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "static", "example.xlsx")

def lesson_to_out(lesson: Lesson) -> LessonOut:
    return LessonOut(
        id=lesson.id,
        group=lesson.group.code if lesson.group else None,
        subject=lesson.subject.title if lesson.subject else None,
        subject_code=lesson.subject.code if lesson.subject else None,
        subject_identifier=lesson.subject.identifier if lesson.subject else None,
        teacher=lesson.teacher.full_name if lesson.teacher else None,
        room=lesson.room.code if lesson.room else None,
        starts_at=lesson.starts_at,
        ends_at=lesson.ends_at,
        subject_type=lesson.subject_type,
        topic=lesson.topic,
        notes=lesson.notes,
        lesson_number=lesson.lesson_number,
    )

@router.get("/template", dependencies=[Depends(require_role_any(["administrator", "director"]))])
def download_schedule_template():
    """Скачать шаблон Excel для импорта расписания."""
    if not os.path.exists(TEMPLATE_PATH):
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    return FileResponse(
        TEMPLATE_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="Шаблон Заполнения Расписания Личного Кабинета.xlsx"
    )

@router.post("/lessons", response_model=LessonOut)
def create_lesson_endpoint(payload: LessonCreate, db: Session = Depends(get_db)):
    lesson = create_lesson(db, payload)
    return lesson_to_out(lesson)

@router.post("/lesson-times", dependencies=[Depends(require_role_any(["administrator", "director"]))])
def create_lesson_time(payload: LessonTimeCreate, db: Session = Depends(get_db)):
    try:
        start_time = time.fromisoformat(payload.start)
        end_time = time.fromisoformat(payload.end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат времени (нужно HH:MM)")

    lt = LessonTime(
        lesson_number=payload.lesson_number,
        start_time=start_time,
        end_time=end_time
    )
    db.add(lt)
    db.commit()
    db.refresh(lt)

    return {
        "id": lt.id,
        "lesson_number": lt.lesson_number,
        "start": str(lt.start_time),
        "end": str(lt.end_time)
    }

@router.get("/lesson-times", dependencies=[Depends(require_role_any(["administrator", "director"]))])
def list_lesson_times(db: Session = Depends(get_db)):
    rows = db.scalars(select(LessonTime).order_by(LessonTime.lesson_number)).all()
    return [
        {"id": r.id, "lesson_number": r.lesson_number, "start": str(r.start_time), "end": str(r.end_time)}
        for r in rows
    ]

@router.post("/lesson-times/{lesson_number}", dependencies=[Depends(require_role_any(["administrator", "director"]))])
def update_lesson_time(
    lesson_number: int,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db)
):
    """Обновить время начала и конца урока."""
    lt = db.scalar(select(LessonTime).where(LessonTime.lesson_number == lesson_number))
    if not lt:
        raise HTTPException(status_code=404, detail="LessonTime not found")

    if start:
        try:
            lt.start_time = time.fromisoformat(start)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат времени для start (HH:MM)")

    if end:
        try:
            lt.end_time = time.fromisoformat(end)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат времени для end (HH:MM)")

    db.commit()
    db.refresh(lt)

    return {
        "lesson_number": lt.lesson_number,
        "start_time": str(lt.start_time),
        "end_time": str(lt.end_time),
    }

@router.post("/import", dependencies=[Depends(require_role_any(["administrator", "director"]))])
def import_schedule(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith((".xls", ".xlsx")):
        raise HTTPException(status_code=400, detail="Файл должен быть Excel (.xls или .xlsx)")

    try:
        import tempfile, shutil
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        count = parse_schedule_excel(tmp_path, db)
        return {"status": "ok", "imported_lessons": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при импорте: {e}")
