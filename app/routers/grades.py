from fastapi import APIRouter, Depends, HTTPException, Response, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError
from datetime import datetime
from openpyxl import Workbook
from io import BytesIO
from urllib.parse import quote
import re

from app.core.deps import get_db, require_permission, get_current_user, is_admin
from app.schemas.grade import GradeCreate, GradeOut, GradeUpdate, FinalGradeIn, FinalGradePatch, GradeTypeFinal, GradeType, SemesterIn
from app.models.grade import Grade, Student
from app.models.schedule import Lesson, Teacher, Subject, teacher_subjects
from app.models.role import Role, user_roles
from app.models.user import User
from app.models.schedule import Group
from app.services.subject_service import resolve_subject

router = APIRouter(prefix="/grades", tags=["grades"])
# Compatibility alias for the endpoint name currently used by frontend.
grated_router = APIRouter(prefix="/grated", tags=["grades"])

FINAL_GRADE_TYPES = ("итог", "final", "exam", "зачет")


def _excel_sheet_title(value: str) -> str:
    title = re.sub(r"[\\/*?:\[\]]", "_", value).strip()
    return (title or "Группа")[:31]


def _validate_final_grade(subject: Subject, grade_type: str, value: str) -> tuple[str, str]:
    expected_type = subject.grade_type
    normalized_type = grade_type.strip().lower().replace("ё", "е")
    normalized_value = value.strip().lower().replace("ё", "е")
    if expected_type not in {"exam", "зачет"}:
        raise HTTPException(status_code=422, detail="Для дисциплины не настроен тип итогового контроля")
    if normalized_type != expected_type:
        raise HTTPException(
            status_code=422,
            detail=f"Тип оценки должен совпадать с типом контроля дисциплины: '{expected_type}'",
        )
    if expected_type == "exam" and normalized_value not in {"2", "3", "4", "5"}:
        raise HTTPException(status_code=422, detail="Для дисциплины с типом 'exam' допустимы только оценки 2, 3, 4 и 5")
    if expected_type == "зачет" and normalized_value not in {"зачет", "не зачет"}:
        raise HTTPException(
            status_code=422,
            detail="Для дисциплины с типом 'зачет' допустимы только 'зачет' и 'не зачет'",
        )
    return expected_type, normalized_value


def _semester_where(year: int | None, season: str | None):
    if year is None or season is None:
        return and_(Grade.semester_year.is_(None), Grade.semester_season.is_(None))
    return and_(Grade.semester_year == year, Grade.semester_season == season)


def _semester_out(grade: Grade) -> SemesterIn | None:
    if grade.semester_year is None or grade.semester_season is None:
        return None
    return SemesterIn(year=grade.semester_year, season=grade.semester_season)


def _grade_out(grade: Grade) -> GradeOut:
    return GradeOut(
        id=grade.id,
        student_id=grade.student_id,
        subject_id=grade.subject_id,
        subject_code=grade.subject.code if grade.subject else None,
        teacher_id=grade.teacher_id,
        lesson_id=grade.lesson_id,
        grade_type=grade.grade_type,
        value=grade.value,
        graded_at=grade.graded_at,
        comment=grade.comment,
        modified_by_admin_id=grade.modified_by_admin_id,
        semester=_semester_out(grade),
    )

def user_has_role(db: Session, user_id: int, role_name: str) -> bool:
    """Проверка роли пользователя."""
    q = (
        select(Role)
        .join(user_roles, Role.id == user_roles.c.role_id)
        .where(user_roles.c.user_id == user_id, Role.name == role_name)
    )
    return db.scalar(q) is not None


@router.post("", response_model=GradeOut, dependencies=[Depends(require_permission("grades:create"))])
@grated_router.post("", response_model=GradeOut, dependencies=[Depends(require_permission("grades:create"))])
def create_grade(payload: GradeCreate, db: Session = Depends(get_db), me=Depends(get_current_user)):
    student = db.get(Student, payload.student_id)
    if not student:
        raise HTTPException(status_code=400, detail="Student not found")

    lesson = db.get(Lesson, payload.lesson_id)
    if not lesson:
        raise HTTPException(status_code=400, detail="Lesson not found")

    if payload.grade_type in FINAL_GRADE_TYPES:
        raise HTTPException(
            status_code=422,
            detail="Итоговую оценку нужно сохранять через /grades/final с типом контроля дисциплины",
        )

    if payload.value not in GradeType:
        raise HTTPException(status_code=400, detail="Недопустимая оценка")

    if student.group_id != lesson.group_id:
        raise HTTPException(status_code=400, detail="Student is not in the lesson's group")

    subj_id = lesson.subject_id
    teacher_profile = db.scalar(select(Teacher).where(Teacher.user_id == me.id))

    is_admin_user = is_admin(me, db)
    is_director_user = user_has_role(db, me.id, "director")
    is_teacher_user = user_has_role(db, me.id, "teacher")

    final_teacher_id = None
    modified_by_admin_id = None

    if payload.grade_type and payload.grade_type.lower() in ["итог", "final", "exam", "зачет"]:
        existing_final = db.scalar(
            select(Grade).where(
                Grade.student_id == student.id,
                Grade.subject_id == subj_id,
                Grade.grade_type.in_(["итог", "final", "exam", "зачет"]),
                _semester_where(
                    payload.semester.year if payload.semester else None,
                    payload.semester.season if payload.semester else None,
                ),
            )
        )
        if existing_final:
            raise HTTPException(status_code=400, detail="Final grade already exists for this subject and student")

    if is_teacher_user and not (is_admin_user or is_director_user):
        if not teacher_profile:
            raise HTTPException(status_code=403, detail="Teacher profile not found")
        if payload.teacher_id != teacher_profile.id:
            raise HTTPException(status_code=403, detail="Teacher can grade only as self")
        if teacher_profile not in lesson.teachers and lesson.teacher_id != teacher_profile.id:
            raise HTTPException(status_code=403, detail="Teacher is not assigned to this lesson")
        is_linked = db.scalar(
            select(teacher_subjects).where(
                teacher_subjects.c.teacher_id == teacher_profile.id,
                teacher_subjects.c.subject_id == subj_id
            )
        )
        if not is_linked and lesson.teacher_id != teacher_profile.id:
            raise HTTPException(status_code=403, detail="Teacher is not assigned to this subject")

        final_teacher_id = teacher_profile.id

    else:
        if payload.teacher_id:
            final_teacher_id = payload.teacher_id
        else:
            final_teacher_id = None
            modified_by_admin_id = me.id

    grade = Grade(
        student_id=student.id,
        subject_id=subj_id,
        teacher_id=final_teacher_id,
        lesson_id=lesson.id,
        grade_type=payload.grade_type,
        value=payload.value,
        graded_at=payload.graded_at or datetime.utcnow(),
        comment=payload.comment,
        modified_by_admin_id=modified_by_admin_id,
        semester_year=payload.semester.year if payload.semester else None,
        semester_season=payload.semester.season if payload.semester else None,
    )
    db.add(grade)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Оценка такого типа для этого занятия уже существует",
        ) from exc
    db.refresh(grade)

    return _grade_out(grade)

@router.get("", response_model=list[GradeOut], dependencies=[Depends(require_permission("grades:read"))])
def list_grades(
    db: Session = Depends(get_db),
    me=Depends(get_current_user),
    grade_type: str | None = None
):
    q = select(Grade)
    if grade_type:
        q = q.where(Grade.grade_type.ilike(f"%{grade_type}%"))
    if user_has_role(db, me.id, "teacher") and not (is_admin(me, db) or user_has_role(db, me.id, "director")):
        teacher_profile = db.scalar(select(Teacher).where(Teacher.user_id == me.id))
        if not teacher_profile:
            raise HTTPException(status_code=403, detail="Teacher profile not found")
        q = q.where(Grade.teacher_id == teacher_profile.id)

    grades = db.scalars(q).all()
    return [_grade_out(g) for g in grades]

@router.post(
    "/final",
    response_model=GradeOut,
    dependencies=[Depends(require_permission("grades:create"))],
)
@grated_router.post(
    "/final",
    response_model=GradeOut,
    dependencies=[Depends(require_permission("grades:create"))],
)
def create_or_update_final_grade(
    payload: FinalGradeIn,
    db: Session = Depends(get_db),
    me=Depends(get_current_user),
):
    """
    Создаёт или обновляет итоговую оценку по предмету.
    Админ, директор или преподаватель (ведущий предмет) могут вызвать.
    """
    student = db.get(Student, payload.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    subject = resolve_subject(db, payload.subject_code, payload.subject_id)
    subject_id = subject.id

    final_type, final_value = _validate_final_grade(
        subject,
        payload.grade_type or subject.grade_type or "",
        payload.value,
    )

    teacher_profile = db.scalar(select(Teacher).where(Teacher.user_id == me.id))
    is_admin_user = is_admin(me, db)
    is_director = db.scalar(
        select(Role)
        .join(user_roles, Role.id == user_roles.c.role_id)
        .where(user_roles.c.user_id == me.id, Role.name == "director")
    )

    if not (is_admin_user or is_director or teacher_profile):
        raise HTTPException(status_code=403, detail="Access denied")

    if teacher_profile and not (is_admin_user or is_director):
        is_linked = db.scalar(
            select(teacher_subjects).where(
                teacher_subjects.c.teacher_id == teacher_profile.id,
                teacher_subjects.c.subject_id == subject_id
            )
        )
        if not is_linked:
            raise HTTPException(status_code=403, detail="Teacher not linked to this subject")

    existing_final = db.scalar(
        select(Grade).where(
            Grade.student_id == payload.student_id,
            Grade.subject_id == subject_id,
            Grade.grade_type.in_(["итог", "final", "exam", "зачет"]),
            _semester_where(
                payload.semester.year if payload.semester else None,
                payload.semester.season if payload.semester else None,
            ),
        )
    )

    if existing_final:
        existing_final.grade_type = final_type
        existing_final.value = final_value
        existing_final.comment = payload.comment
        existing_final.graded_at = datetime.utcnow()
        db.commit()
        db.refresh(existing_final)
        return _grade_out(existing_final)

    final_grade = Grade(
        student_id=payload.student_id,
        subject_id=subject_id,
        teacher_id=teacher_profile.id if teacher_profile else None,
        lesson_id=None,
        grade_type=final_type,
        value=final_value,
        graded_at=datetime.utcnow(),
        comment=payload.comment,
        modified_by_admin_id=me.id if (is_admin_user or is_director) else None,
        semester_year=payload.semester.year if payload.semester else None,
        semester_season=payload.semester.season if payload.semester else None,
    )

    db.add(final_grade)
    db.commit()
    db.refresh(final_grade)

    return _grade_out(final_grade)

@router.post(
    "/final/{student_id}/{subject_code}",
    response_model=GradeOut,
    dependencies=[Depends(require_permission("grades:update"))],
)
@grated_router.post(
    "/final/{student_id}/{subject_code}",
    response_model=GradeOut,
    dependencies=[Depends(require_permission("grades:update"))],
)
def patch_final_grade(
    student_id: int,
    subject_code: str,
    payload: FinalGradePatch,
    db: Session = Depends(get_db),
    me=Depends(get_current_user),
):
    """
    Обновляет итоговую оценку (value, comment).
    Доступно админу, директору и преподавателю (если он связан с предметом).
    """
    student = db.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    subject = resolve_subject(db, subject_code=subject_code)
    subject_id = subject.id

    requested_type = payload.grade_type or subject.grade_type
    requested_value = payload.value

    teacher_profile = db.scalar(select(Teacher).where(Teacher.user_id == me.id))
    is_admin_user = is_admin(me, db)
    is_director = db.scalar(
        select(Role)
        .join(user_roles, Role.id == user_roles.c.role_id)
        .where(user_roles.c.user_id == me.id, Role.name == "director")
    )

    if not (is_admin_user or is_director or teacher_profile):
        raise HTTPException(status_code=403, detail="Access denied")

    if teacher_profile and not (is_admin_user or is_director):
        is_linked = db.scalar(
            select(teacher_subjects).where(
                teacher_subjects.c.teacher_id == teacher_profile.id,
                teacher_subjects.c.subject_id == subject_id,
            )
        )
        if not is_linked:
            raise HTTPException(status_code=403, detail="Teacher not linked to this subject")

    final_grade = db.scalar(
        select(Grade).where(
            Grade.student_id == student_id,
            Grade.subject_id == subject_id,
            Grade.grade_type.in_(["итог", "final", "exam", "зачет"]),
            _semester_where(
                payload.semester.year if payload.semester else None,
                payload.semester.season if payload.semester else None,
            ),
        )
    )

    if not final_grade:
        raise HTTPException(status_code=404, detail="Final grade not found")

    if requested_value is not None:
        final_type, final_value = _validate_final_grade(subject, requested_type, requested_value)
        final_grade.grade_type = final_type
        final_grade.value = final_value
    elif payload.grade_type is not None and payload.grade_type != subject.grade_type:
        raise HTTPException(status_code=422, detail="Тип оценки должен совпадать с типом контроля дисциплины")
    if payload.comment is not None:
        final_grade.comment = payload.comment

    final_grade.graded_at = datetime.utcnow()
    if is_admin_user or is_director:
        final_grade.modified_by_admin_id = me.id

    db.commit()
    db.refresh(final_grade)

    return _grade_out(final_grade)

@router.post("/{grade_id}", response_model=GradeOut, dependencies=[Depends(require_permission("grades:update"))])
def update_grade(
    grade_id: int,
    payload: GradeUpdate,
    db: Session = Depends(get_db),
    me = Depends(get_current_user),
):
    grade = db.get(Grade, grade_id)
    if not grade:
        raise HTTPException(status_code=404, detail="Grade not found")

    is_admin_user = is_admin(me, db)
    is_director = user_has_role(db, me.id, "director")
    is_teacher = user_has_role(db, me.id, "teacher")

    if grade.lesson_id is None and (payload.grade_type is not None or payload.value is not None):
        subject = resolve_subject(
            db,
            payload.subject_code,
            payload.subject_id or grade.subject_id,
        )
        final_type, final_value = _validate_final_grade(
            subject,
            payload.grade_type or grade.grade_type,
            payload.value or grade.value,
        )
        payload.grade_type = final_type
        payload.value = final_value
    elif grade.lesson_id is not None and payload.grade_type in FINAL_GRADE_TYPES:
        raise HTTPException(status_code=422, detail="Оценка за занятие должна иметь тип 'текущая'")

    if is_teacher and not (is_admin_user or is_director):
        teacher_profile = db.scalar(select(Teacher).where(Teacher.user_id == me.id))
        if not teacher_profile:
            raise HTTPException(status_code=403, detail="Teacher profile not found")

        if grade.teacher_id != teacher_profile.id:
            lesson = db.get(Lesson, grade.lesson_id)
            if not lesson or teacher_profile not in lesson.teachers:
                raise HTTPException(status_code=403, detail="Cannot edit grade of another teacher")


        if any([payload.subject_code is not None, payload.subject_id is not None, payload.lesson_id is not None, payload.teacher_id is not None]):
            raise HTTPException(status_code=403, detail="Teacher cannot change subject/lesson/teacher fields")

        if payload.grade_type is not None:
            grade.grade_type = payload.grade_type
        if payload.value is not None:
            grade.value = payload.value
        if payload.comment is not None:
            grade.comment = payload.comment
        if payload.graded_at is not None:
            grade.graded_at = payload.graded_at

    else:
        if payload.teacher_id is not None:
            grade.teacher_id = payload.teacher_id

        if payload.subject_code is not None or payload.subject_id is not None:
            grade.subject_id = resolve_subject(db, payload.subject_code, payload.subject_id).id

        if payload.lesson_id is not None:
            lesson = db.get(Lesson, payload.lesson_id)
            if not lesson:
                raise HTTPException(status_code=400, detail="Lesson not found")
            student = db.get(Student, grade.student_id)
            if student and student.group_id != lesson.group_id:
                raise HTTPException(status_code=400, detail="Student is not in the new lesson's group")
            grade.lesson_id = payload.lesson_id

        if payload.grade_type is not None:
            grade.grade_type = payload.grade_type
        if payload.value is not None:
            grade.value = payload.value
        if payload.comment is not None:
            grade.comment = payload.comment
        if payload.graded_at is not None:
            grade.graded_at = payload.graded_at

    db.commit()
    db.refresh(grade)

    return _grade_out(grade)


@router.get("/export", dependencies=[Depends(require_permission("grades:read"))])
def export_grades_excel(
    db: Session = Depends(get_db),
    year: int | None = Query(None, ge=2000, le=2200, description="Год учебного семестра"),
    season: str | None = Query(None, description="весна или осень"),
    group_id: int | None = Query(None, ge=1, description="ID группы"),
    group_code: str | None = Query(None, description="Код группы, например ИТ-24-1"),
    from_date: datetime | None = Query(None, description="Начало периода (включительно)"),
    to_date: datetime | None = Query(None, description="Конец периода (включительно)"),
    teacher_id: int | None = Query(None, description="ID преподавателя"),
    subject_code: str | None = Query(None, description="Код дисциплины"),
    subject_id: int | None = Query(None, description="ID предмета"),
    grade_type: str | None = Query(None, description="Тип оценки (например 'итог', 'текущая')"),
):
    """
    📘 Выгрузка ведомостей по всем предметам в Excel.
    Фильтры: по группе, семестру, предмету, преподавателю и типу оценки.
    Каждый лист — отдельная группа.
    """
    if season is not None:
        season = season.strip().lower().replace("ё", "е")
        if season not in {"весна", "осень"}:
            raise HTTPException(status_code=422, detail="season должен быть 'весна' или 'осень'")
    if (year is None) != (season is None):
        raise HTTPException(status_code=422, detail="year и season должны передаваться вместе")
    if year is None and (from_date or to_date):
        reference_date = from_date or to_date
        year = reference_date.year
        season = "весна" if reference_date.month <= 6 else "осень"
    if year is None:
        raise HTTPException(status_code=422, detail="Укажите учебный семестр через year и season")

    resolved_subject_id = (
        resolve_subject(db, subject_code=subject_code).id
        if subject_code
        else subject_id
    )

    groups_stmt = select(Group).order_by(Group.code)
    normalized_group_code = group_code.strip() if group_code else None
    if group_id is not None:
        groups_stmt = groups_stmt.where(Group.id == group_id)
    if normalized_group_code:
        groups_stmt = groups_stmt.where(Group.code == normalized_group_code)

    groups = db.scalars(groups_stmt).all()
    if not groups:
        if group_id is not None or normalized_group_code:
            raise HTTPException(
                status_code=404,
                detail="Группа с указанными group_id/group_code не найдена",
            )
        raise HTTPException(status_code=404, detail="Группы не найдены")

    wb = Workbook()
    wb.remove(wb.active)

    for group in groups:
        ws = wb.create_sheet(title=_excel_sheet_title(group.code or group.title))
        ws.append([
            "№", "ФИО студента", "Предмет", "Тип оценки",
            "Оценка", "Комментарий", "Преподаватель", "Дата выставления"
        ])

        students = db.scalars(select(Student).where(Student.group_id == group.id)).all()
        row_num = 1
        exam_values: list[int] = []
        passed_count = 0
        failed_count = 0
        not_graded_count = 0
        group_subjects_stmt = (
            select(Subject)
            .join(Lesson, Lesson.subject_id == Subject.id)
            .where(Lesson.group_id == group.id, Subject.grade_type.in_(["exam", "зачет"]))
            .distinct()
        )
        if resolved_subject_id:
            group_subjects_stmt = group_subjects_stmt.where(Subject.id == resolved_subject_id)
        if teacher_id:
            group_subjects_stmt = group_subjects_stmt.where(Lesson.teacher_id == teacher_id)
        if grade_type in {"exam", "зачет"}:
            group_subjects_stmt = group_subjects_stmt.where(Subject.grade_type == grade_type)
        group_subjects = db.scalars(group_subjects_stmt).all()

        for student in students:
            q = select(Grade).join(Subject, Subject.id == Grade.subject_id)
            q = q.where(Grade.student_id == student.id)

            q = q.where(Grade.semester_year == year, Grade.semester_season == season)
            if teacher_id:
                q = q.where(Grade.teacher_id == teacher_id)
            if resolved_subject_id:
                q = q.where(Grade.subject_id == resolved_subject_id)
            if grade_type:
                q = q.where(Grade.grade_type.ilike(f"%{grade_type}%"))

            grades = db.scalars(q).all()

            student_user = db.get(User, student.user_id)
            student_name = student_user.full_name or "—"
            final_subject_ids: set[int] = set()

            for g in grades:
                teacher_name = ""
                if g.teacher_id:
                    teacher = db.get(Teacher, g.teacher_id)
                    if teacher and teacher.full_name:
                        teacher_name = teacher.full_name
                    elif teacher and teacher.user_id:
                        u = db.get(User, teacher.user_id)
                        teacher_name = u.full_name or ""

                control_type = g.subject.grade_type if g.subject else None
                normalized_value = (g.value or "").strip().lower().replace("ё", "е")
                display_value = g.value
                if control_type == "зачет" and g.grade_type == "зачет":
                    if normalized_value == "зачет":
                        display_value = "Зачёт"
                        passed_count += 1
                    elif normalized_value == "не зачет":
                        display_value = "Не зачёт"
                        failed_count += 1
                    else:
                        display_value = "Не выставлено"
                elif control_type == "exam" and g.grade_type == "exam" and normalized_value in {"2", "3", "4", "5"}:
                    exam_values.append(int(normalized_value))
                if g.grade_type in {"exam", "зачет"} and g.subject_id is not None:
                    final_subject_ids.add(g.subject_id)

                ws.append([
                    row_num,
                    student_name,
                    g.subject.title if g.subject else "",
                    control_type or g.grade_type,
                    display_value,
                    g.comment or "",
                    teacher_name,
                    g.graded_at.strftime("%d.%m.%Y %H:%M") if g.graded_at else "",
                ])
                row_num += 1

            for missing_subject in group_subjects:
                if missing_subject.id in final_subject_ids:
                    continue
                ws.append([
                    row_num,
                    student_name,
                    missing_subject.title,
                    missing_subject.grade_type,
                    "Не выставлено",
                    "",
                    "",
                    "",
                ])
                row_num += 1
                not_graded_count += 1

        ws.append([])
        if exam_values:
            ws.append(["Средний балл (экзамены)", sum(exam_values) / len(exam_values)])
        ws.append(["Зачёт", passed_count])
        ws.append(["Не зачёт", failed_count])
        ws.append(["Не выставлено", not_graded_count])

        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            ws.column_dimensions[col_letter].width = max_len + 2

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)

    group_suffix = f"_{groups[0].code}" if len(groups) == 1 else ""
    filename = f"vedomost{group_suffix}_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.xlsx"
    encoded_filename = quote(filename)

    return Response(
        content=stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="vedomost.xlsx"; filename*=UTF-8\'\'{encoded_filename}'
            )
        },
    )
