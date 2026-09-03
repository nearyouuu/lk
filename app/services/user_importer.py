from __future__ import annotations

import os
import re
import secrets
import tempfile
from copy import copy
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.grade import Student
from app.models.profile import AdminProfile, Director
from app.models.role import Role, user_roles
from app.models.schedule import Group, Room, Subject, Subdivision, Teacher
from app.models.subject_type import SubjectType
from app.models.user import User


SHEET_ALIASES = {
    "users": {"пользователи", "users", "сотрудники", "студенты"},
    "groups": {"группы", "groups"},
    "subdivisions": {"подразделения", "subdivisions", "кафедры"},
    "rooms": {"аудитории", "rooms", "кабинеты"},
    "subjects": {"дисциплины", "subjects", "предметы"},
}
USER_COLUMNS = {
    "full_name": ("фио", "full name", "full_name"),
    "email": ("электронная почта", "email", "e-mail"),
    "role": ("роль", "role"),
    "phone": ("телефон", "phone"),
    "birth_date": ("дата рождения", "birth date", "birth_date"),
    "group_identifier": (
        "идентификатор группы", "group identifier", "group_identifier",
        "группа", "group", "код группы",
    ),
    "subject": ("предмет", "subject"),
    "subdivision": ("подразделение", "код подразделения", "subdivision"),
    "record_book": ("номер зачетки", "номер зачётки", "record book", "record_book"),
    "insert_year": ("год поступления", "insert year", "insert_year"),
    "course": ("курс", "course"),
}
GROUP_COLUMNS = {
    "identifier": ("идентификатор группы", "group identifier", "group_identifier", "identifier", "id группы"),
    "code": ("код группы", "код", "group code", "code"),
    "title": ("название группы", "название", "group title", "title"),
}
SUBDIVISION_COLUMNS = {
    "code": ("код подразделения", "код", "subdivision code", "code"),
    "name": ("название подразделения", "название", "name"),
    "type": ("тип подразделения", "тип", "type"),
    "parent_code": ("код родительского подразделения", "родитель", "parent code", "parent_code"),
}
ROOM_COLUMNS = {
    "code": ("код аудитории", "код", "room code", "code"),
    "title": ("название аудитории", "название", "room title", "title"),
    "capacity": ("вместимость", "capacity"),
}
SUBJECT_COLUMNS = {
    "code": ("код дисциплины", "код", "subject code", "code"),
    "title": ("название дисциплины", "название", "subject title", "title"),
    "type": ("тип дисциплины", "тип", "subject type", "type"),
    "primary_teacher": ("email основного преподавателя", "основной преподаватель", "primary teacher", "primary_teacher"),
    "teachers": ("email преподавателей", "преподаватели", "teachers"),
}
ROLE_ALIASES = {
    "студент": "student",
    "student": "student",
    "преподаватель": "teacher",
    "учитель": "teacher",
    "teacher": "teacher",
    "директор": "director",
    "director": "director",
    "администратор": "administrator",
    "admin": "administrator",
    "administrator": "administrator",
}


@dataclass(frozen=True)
class ImportResult:
    report_path: str
    created: int
    skipped: int
    failed: int
    groups_created: int
    subdivisions_created: int
    rooms_created: int
    subjects_created: int
    subject_types_created: int


def _text(value: Any) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _header(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value).lower().replace("ё", "е"))


def _column_map(frame: pd.DataFrame, aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    actual = {_header(column): column for column in frame.columns}
    result: dict[str, str] = {}
    for canonical, variants in aliases.items():
        for variant in variants:
            found = actual.get(_header(variant))
            if found is not None:
                result[canonical] = found
                break
    return result


def _value(row: pd.Series, columns: dict[str, str], key: str) -> str:
    column = columns.get(key)
    return _text(row[column]) if column else ""


def _parse_date(value: Any) -> date | None:
    if not _text(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        raise ValueError("некорректная дата рождения")
    return parsed.date()


def _parse_capacity(value: str) -> int | None:
    if not value:
        return None
    try:
        capacity = int(value)
    except ValueError as exc:
        raise ValueError("вместимость должна быть целым числом") from exc
    if capacity <= 0:
        raise ValueError("вместимость должна быть больше нуля")
    return capacity


def _valid_email(value: str) -> str:
    email = value.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 255:
        raise ValueError("некорректный email")
    return email


def _email_list(value: str) -> list[str]:
    if not value:
        return []
    result: list[str] = []
    for part in re.split(r"[,;\n]+", value):
        email = _valid_email(part.strip())
        if email not in result:
            result.append(email)
    return result


def _require_group_identifier(value: str) -> str:
    identifier = value.strip()
    if not identifier:
        raise ValueError("для студента не указана группа")
    return identifier


def _get_or_create_group(
    db: Session, identifier: str, code: str, title: str
) -> tuple[Group, bool]:
    group = db.scalar(select(Group).where(Group.identifier == identifier))
    if group:
        return group, False
    group = Group(identifier=identifier, code=code, title=title or code)
    db.add(group)
    db.flush()
    return group, True


def _find_subdivision(db: Session, value: str) -> Subdivision | None:
    if not value:
        return None
    return db.scalar(
        select(Subdivision).where(
            (func.lower(Subdivision.code) == value.lower())
            | (func.lower(Subdivision.name) == value.lower())
        )
    )


def _find_teacher(db: Session, email: str) -> Teacher | None:
    return db.scalar(select(Teacher).where(func.lower(Teacher.email) == email.lower()))


def _read_workbook(file_path: str) -> tuple[dict[str, pd.DataFrame], set[str]]:
    try:
        source = pd.read_excel(file_path, sheet_name=None, dtype=object)
    except Exception as exc:
        raise ValueError(f"не удалось прочитать Excel-файл: {exc}") from exc
    if not source:
        raise ValueError("Excel-файл не содержит листов")

    frames = {key: pd.DataFrame() for key in SHEET_ALIASES}
    present: set[str] = set()
    for sheet_name, frame in source.items():
        normalized = _header(sheet_name)
        for key, aliases in SHEET_ALIASES.items():
            if normalized in aliases:
                present.add(key)
                combined = pd.concat([frames[key], frame], ignore_index=True)
                frames[key] = combined.where(combined.notna(), "")
                break

    # Обратная совместимость со старым одно-листовым шаблоном.
    if not present:
        for frame in source.values():
            if {"full_name", "email", "role"}.issubset(_column_map(frame, USER_COLUMNS)):
                frames["users"] = frame.fillna("")
                present.add("users")
                break
    if not present:
        names = "Пользователи, Группы, Подразделения, Аудитории или Дисциплины"
        raise ValueError(f"не найден поддерживаемый лист: {names}")
    return frames, present


def _write_report(path: str, reports: dict[str, list[dict[str, Any]]]) -> None:
    sheet_names = {
        "users": "Пользователи",
        "groups": "Группы",
        "subdivisions": "Подразделения",
        "rooms": "Аудитории",
        "subjects": "Дисциплины",
    }
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for key, sheet_name in sheet_names.items():
            rows = reports[key] or [{"Статус": "Нет строк для импорта"}]
            pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)
        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for cell in worksheet[1]:
                font = copy(cell.font)
                font.bold = True
                font.color = "FFFFFF"
                cell.font = font
                fill = copy(cell.fill)
                fill.fill_type = "solid"
                fill.fgColor.rgb = "1F4E78"
                cell.fill = fill
            for column in worksheet.columns:
                width = min(max(len(_text(cell.value)) for cell in column) + 2, 45)
                worksheet.column_dimensions[column[0].column_letter].width = max(width, 12)


def _validate_columns(frames: dict[str, pd.DataFrame], present: set[str]) -> dict[str, dict[str, str]]:
    display_names = {
        "users": "Пользователи",
        "groups": "Группы",
        "subdivisions": "Подразделения",
        "rooms": "Аудитории",
        "subjects": "Дисциплины",
    }
    definitions = {
        "users": (USER_COLUMNS, {"full_name", "email", "role"}, "ФИО, Электронная почта, Роль"),
        "groups": (
            GROUP_COLUMNS,
            {"identifier", "code", "title"},
            "Идентификатор группы, Код группы, Название группы",
        ),
        "subdivisions": (SUBDIVISION_COLUMNS, {"name"}, "Название подразделения"),
        "rooms": (ROOM_COLUMNS, {"code"}, "Код аудитории"),
        "subjects": (SUBJECT_COLUMNS, {"title"}, "Название дисциплины"),
    }
    result: dict[str, dict[str, str]] = {}
    for key, (aliases, required, required_names) in definitions.items():
        result[key] = _column_map(frames[key], aliases)
        if key in present and not required.issubset(result[key]):
            raise ValueError(f"на листе «{display_names[key]}» обязательны колонки: {required_names}")
    return result


def import_users_from_excel(db: Session, file_path: str, export_dir: str = "exports") -> ImportResult:
    """Импортирует справочники и пользователей, возвращая подробный Excel-отчёт."""
    frames, present = _read_workbook(file_path)
    columns = _validate_columns(frames, present)
    reports: dict[str, list[dict[str, Any]]] = {key: [] for key in SHEET_ALIASES}

    created = skipped = failed = 0
    groups_created = subdivisions_created = rooms_created = subjects_created = subject_types_created = 0

    try:
        # 1. Подразделения создаются до преподавателей. Родители назначаются вторым проходом.
        pending_parents: list[tuple[Subdivision, str, dict[str, Any]]] = []
        for index, row in frames["subdivisions"].iterrows():
            code = _value(row, columns["subdivisions"], "code")
            name = _value(row, columns["subdivisions"], "name")
            subdivision_type = _value(row, columns["subdivisions"], "type") or None
            parent_code = _value(row, columns["subdivisions"], "parent_code")
            report = {"Строка": index + 2, "Код": code, "Название": name, "Тип": subdivision_type or "", "Родитель": parent_code}
            try:
                if not name:
                    raise ValueError("не указано название подразделения")
                if parent_code and code and parent_code.lower() == code.lower():
                    raise ValueError("подразделение не может быть родителем самому себе")
                existing = _find_subdivision(db, code or name)
                if existing:
                    report.update({"Статус": "Пропущено", "Комментарий": "подразделение уже существует"})
                else:
                    subdivision = Subdivision(name=name, code=code or None, type=subdivision_type)
                    db.add(subdivision)
                    db.flush()
                    pending_parents.append((subdivision, parent_code, report))
                    subdivisions_created += 1
                    report.update({"Статус": "Создано", "Комментарий": ""})
            except ValueError as exc:
                failed += 1
                report.update({"Статус": "Ошибка", "Комментарий": str(exc)})
            reports["subdivisions"].append(report)

        for subdivision, parent_code, report in pending_parents:
            if not parent_code:
                continue
            parent = _find_subdivision(db, parent_code)
            if parent is None:
                db.delete(subdivision)
                subdivisions_created -= 1
                failed += 1
                report.update({"Статус": "Ошибка", "Комментарий": f"родительское подразделение «{parent_code}» не найдено"})
            else:
                subdivision.parent_id = parent.id
        db.flush()

        # 2. Группы.
        for index, row in frames["groups"].iterrows():
            identifier = _value(row, columns["groups"], "identifier")
            code = _value(row, columns["groups"], "code")
            title = _value(row, columns["groups"], "title")
            report = {"Строка": index + 2, "Идентификатор группы": identifier, "Код группы": code, "Название группы": title}
            if not identifier:
                failed += 1
                report.update({"Статус": "Ошибка", "Комментарий": "не указан идентификатор группы"})
            elif not code:
                failed += 1
                report.update({"Статус": "Ошибка", "Комментарий": "не указан код группы"})
            elif not title:
                failed += 1
                report.update({"Статус": "Ошибка", "Комментарий": "не указано название группы"})
            else:
                _, was_created = _get_or_create_group(db, identifier, code, title)
                groups_created += int(was_created)
                report.update({"Статус": "Создана" if was_created else "Пропущена", "Комментарий": "" if was_created else "группа уже существует"})
            reports["groups"].append(report)

        # 3. Пользователи и профили.
        seen_emails: set[str] = set()
        for index, row in frames["users"].iterrows():
            full_name = _value(row, columns["users"], "full_name")
            email_raw = _value(row, columns["users"], "email")
            role_raw = _value(row, columns["users"], "role")
            report = {"Строка": index + 2, "ФИО": full_name, "Email": email_raw, "Роль": role_raw, "Статус": "Ошибка", "Комментарий": "", "Пароль": ""}
            try:
                if not full_name:
                    raise ValueError("не указано ФИО")
                email = _valid_email(email_raw)
                role_name = ROLE_ALIASES.get(_header(role_raw))
                if not role_name:
                    raise ValueError("неизвестная роль; допустимы: студент, преподаватель, директор, администратор")
                if email in seen_emails:
                    raise ValueError("email повторяется в файле")
                seen_emails.add(email)
                if db.scalar(select(User.id).where(User.email == email)) is not None:
                    skipped += 1
                    report.update({"Статус": "Пропущен", "Комментарий": "пользователь с таким email уже существует"})
                    reports["users"].append(report)
                    continue

                role = db.scalar(select(Role).where(Role.name == role_name))
                if role is None:
                    raise ValueError(f"роль «{role_name}» не настроена в системе")
                phone = _value(row, columns["users"], "phone") or None
                birth_date = _parse_date(row[columns["users"]["birth_date"]]) if columns["users"].get("birth_date") else None
                group = None
                if role_name == "student":
                    group_identifier = _require_group_identifier(
                        _value(row, columns["users"], "group_identifier")
                    )
                    group = db.scalar(
                        select(Group).where(Group.identifier == group_identifier)
                    )
                    if group is None:
                        raise ValueError(
                            f"группа с идентификатором «{group_identifier}» не найдена; "
                            "сначала добавьте её на лист «Группы»"
                        )
                subdivision = None
                if role_name == "teacher" and _value(row, columns["users"], "subdivision"):
                    subdivision_value = _value(row, columns["users"], "subdivision")
                    subdivision = _find_subdivision(db, subdivision_value)
                    if subdivision is None:
                        raise ValueError(f"подразделение «{subdivision_value}» не найдено")

                raw_password = secrets.token_urlsafe(9)
                user = User(email=email, full_name=full_name, phone=phone, birth_date=birth_date, password_hash=hash_password(raw_password), is_active=True)
                db.add(user)
                db.flush()
                db.execute(user_roles.insert().values(user_id=user.id, role_id=role.id))

                if role_name == "student":
                    db.add(Student(user_id=user.id, group_id=group.id, record_book=_value(row, columns["users"], "record_book") or None, insert_year=_value(row, columns["users"], "insert_year") or None, course=_value(row, columns["users"], "course") or None))
                elif role_name == "teacher":
                    db.add(Teacher(user_id=user.id, full_name=full_name, email=email, phone=phone, subject=_value(row, columns["users"], "subject") or None, subdivision_id=subdivision.id if subdivision else None))
                elif role_name == "director":
                    db.add(Director(user_id=user.id, full_name=full_name, email=email, phone=phone))
                else:
                    db.add(AdminProfile(user_id=user.id))
                db.flush()
                created += 1
                report.update({"Email": email, "Статус": "Создан", "Пароль": raw_password})
            except ValueError as exc:
                failed += 1
                report["Комментарий"] = str(exc)
            reports["users"].append(report)

        # 4. Аудитории.
        for index, row in frames["rooms"].iterrows():
            code = _value(row, columns["rooms"], "code")
            title = _value(row, columns["rooms"], "title") or code
            capacity_raw = _value(row, columns["rooms"], "capacity")
            report = {"Строка": index + 2, "Код": code, "Название": title, "Вместимость": capacity_raw}
            try:
                if not code:
                    raise ValueError("не указан код аудитории")
                capacity = _parse_capacity(capacity_raw)
                if db.scalar(select(Room.id).where(Room.code == code)) is not None:
                    report.update({"Статус": "Пропущена", "Комментарий": "аудитория уже существует"})
                else:
                    db.add(Room(code=code, title=title, capacity=capacity))
                    db.flush()
                    rooms_created += 1
                    report.update({"Статус": "Создана", "Комментарий": ""})
            except ValueError as exc:
                failed += 1
                report.update({"Статус": "Ошибка", "Комментарий": str(exc)})
            reports["rooms"].append(report)

        # 5. Дисциплины и связи с преподавателями.
        for index, row in frames["subjects"].iterrows():
            code = _value(row, columns["subjects"], "code")
            title = _value(row, columns["subjects"], "title")
            type_name = _value(row, columns["subjects"], "type")
            primary_email = _value(row, columns["subjects"], "primary_teacher")
            teachers_raw = _value(row, columns["subjects"], "teachers")
            report = {"Строка": index + 2, "Код": code, "Название": title, "Тип": type_name, "Основной преподаватель": primary_email, "Преподаватели": teachers_raw}
            try:
                if not code:
                    raise ValueError("не указан код дисциплины")
                if not title:
                    raise ValueError("не указано название дисциплины")
                duplicate = db.scalar(select(Subject.id).where(Subject.code == code))
                if duplicate is not None:
                    report.update({"Статус": "Пропущена", "Комментарий": "дисциплина уже существует"})
                    reports["subjects"].append(report)
                    continue

                primary_teacher = None
                if primary_email:
                    primary_email = _valid_email(primary_email)
                    primary_teacher = _find_teacher(db, primary_email)
                    if primary_teacher is None:
                        raise ValueError(f"основной преподаватель «{primary_email}» не найден")
                teacher_emails = _email_list(teachers_raw)
                if primary_email and primary_email not in teacher_emails:
                    teacher_emails.insert(0, primary_email)
                teachers: list[Teacher] = []
                for email in teacher_emails:
                    teacher = _find_teacher(db, email)
                    if teacher is None:
                        raise ValueError(f"преподаватель «{email}» не найден")
                    if teacher not in teachers:
                        teachers.append(teacher)
                if teachers and primary_teacher is None:
                    primary_teacher = teachers[0]

                subject_type = None
                if type_name:
                    subject_type = db.scalar(select(SubjectType).where(func.lower(SubjectType.name) == type_name.lower()))
                    if subject_type is None:
                        subject_type = SubjectType(name=type_name)
                        db.add(subject_type)
                        db.flush()
                        subject_types_created += 1

                # The legacy catalog category is kept for import compatibility,
                # but a discipline is no longer linked to lesson kinds.
                subject = Subject(
                    code=code or None,
                    title=title,
                    primary_teacher_id=primary_teacher.id if primary_teacher else None,
                )
                db.add(subject)
                db.flush()
                for teacher in teachers:
                    if teacher not in subject.teachers:
                        subject.teachers.append(teacher)
                subjects_created += 1
                report.update({"Статус": "Создана", "Комментарий": ""})
            except ValueError as exc:
                failed += 1
                report.update({"Статус": "Ошибка", "Комментарий": str(exc)})
            reports["subjects"].append(report)

        os.makedirs(export_dir, exist_ok=True)
        handle, report_path = tempfile.mkstemp(prefix="import_result_", suffix=".xlsx", dir=export_dir)
        os.close(handle)
        try:
            _write_report(report_path, reports)
            db.commit()
        except Exception:
            if os.path.exists(report_path):
                os.remove(report_path)
            raise
    except Exception:
        db.rollback()
        raise

    return ImportResult(
        report_path=report_path,
        created=created,
        skipped=skipped,
        failed=failed,
        groups_created=groups_created,
        subdivisions_created=subdivisions_created,
        rooms_created=rooms_created,
        subjects_created=subjects_created,
        subject_types_created=subject_types_created,
    )
