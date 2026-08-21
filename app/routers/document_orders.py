import os
from datetime import date, datetime, time, timedelta
from io import BytesIO
from typing import Optional
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from openpyxl import Workbook
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db, require_admin, require_feature, require_role_any
from app.models.document_order import DocumentOrder
from app.models.grade import Student as StudentModel
from app.models.role import Role, user_roles
from app.models.schedule import Group
from app.models.user import User
from app.schemas.document_order import (
    DocumentOrderCreate,
    DocumentOrderExportLinkCreate,
    DocumentOrderExportLinkOut,
    DocumentOrderOut,
    DocumentOrderUpdate,
    ENUM_VALUES,
    OrderType,
    OrderStatus,
)
from app.services.document_order_export_link import (
    create_export_link_token,
    decode_export_link_token,
)


def _validation_message(exc: RequestValidationError) -> str:
    error = exc.errors()[0]
    location = error.get("loc", ())
    field = str(location[-1]) if location else "request"
    error_type = error.get("type", "")
    if error_type == "missing":
        return f"Обязательное поле не заполнено: {field}"
    if error_type in {"int_type", "int_parsing"}:
        return f"Поле {field} должно быть целым числом"
    if error_type == "string_type":
        return f"Поле {field} должно быть строкой"
    if error_type == "literal_error":
        return f"Недопустимое значение поля {field}"
    if error_type in {"dict_type", "model_attributes_type"}:
        return "Тело запроса должно быть JSON-объектом"
    if error_type == "json_invalid":
        return "Некорректный JSON"
    message = error.get("msg", "Ошибка валидации")
    if message.startswith("Value error, "):
        message = message.removeprefix("Value error, ")
    return message


class DetailStringRoute(APIRoute):
    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request):
            try:
                return await original_route_handler(request)
            except RequestValidationError as exc:
                raise HTTPException(status_code=422, detail=_validation_message(exc)) from exc

        return custom_route_handler


router = APIRouter(
    prefix="/document-orders",
    tags=["document_orders"],
    dependencies=[Depends(require_feature("applications"))],
    route_class=DetailStringRoute,
)


def _student_for_user(db: Session, user: User) -> StudentModel:
    student = db.scalar(select(StudentModel).where(StudentModel.user_id == user.id))
    if not student:
        raise HTTPException(status_code=403, detail="Профиль студента не найден")
    return student


def _role_names(db: Session, user_id: int) -> set[str]:
    return set(
        db.scalars(
            select(Role.name)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == user_id)
        ).all()
    )


def _filtered_orders_statement(
    *,
    order_type: OrderType | None = None,
    status: OrderStatus | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    group_name: str | None = None,
    student_id: int | None = None,
    q: str | None = None,
):
    if created_from and created_to and created_from > created_to:
        raise HTTPException(
            status_code=422,
            detail="Дата начала периода не может быть позже даты окончания",
        )

    statement = select(DocumentOrder)
    if order_type:
        statement = statement.where(DocumentOrder.order_type == order_type)
    if status:
        statement = statement.where(DocumentOrder.status == status)
    if created_from:
        statement = statement.where(
            DocumentOrder.created_at >= datetime.combine(created_from, time.min)
        )
    if created_to:
        statement = statement.where(
            DocumentOrder.created_at < datetime.combine(created_to + timedelta(days=1), time.min)
        )
    if group_name:
        statement = statement.where(DocumentOrder.group_name == group_name.strip())
    if student_id is not None:
        statement = statement.where(DocumentOrder.student_id == student_id)
    if q and q.strip():
        search = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                DocumentOrder.full_name.ilike(search),
                DocumentOrder.group_name.ilike(search),
                DocumentOrder.request_text.ilike(search),
            )
        )
    return statement.order_by(DocumentOrder.created_at.desc())


def _excel_safe(value) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


def _book_orders_workbook(orders: list[DocumentOrder]) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Заявки на книги"
    sheet.append([
        "Номер заявки",
        "Дата",
        "ФИО студента",
        "Группа",
        "Текст заявки",
        "Статус",
        "Комментарий администратора",
    ])
    for order in orders:
        sheet.append([
            order.id,
            order.created_at.strftime("%d.%m.%Y %H:%M"),
            _excel_safe(order.full_name),
            _excel_safe(order.group_name),
            _excel_safe(order.request_text),
            order.status,
            _excel_safe(order.comment_admin),
        ])

    widths = (16, 20, 32, 18, 70, 20, 40)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + index)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


def _book_export_response(orders: list[DocumentOrder]) -> StreamingResponse:
    filename = f"book_delivery_orders_{date.today().isoformat()}.xlsx"
    return StreamingResponse(
        _book_orders_workbook(orders),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


@router.post(
    "",
    response_model=DocumentOrderOut,
    status_code=201,
    dependencies=[Depends(require_role_any(["student"]))],
)
async def create_document_order(
    data: DocumentOrderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    student = _student_for_user(db, user)
    full_name = (user.full_name or "").strip()
    if not full_name:
        raise HTTPException(status_code=422, detail="В профиле студента не указано ФИО")

    group = db.get(Group, student.group_id)
    group_name = (group.code if group else "").strip()
    if not group_name:
        raise HTTPException(status_code=422, detail="Группа студента не найдена")

    order = DocumentOrder(
        student_id=student.id,
        full_name=full_name,
        order_type=data.order_type,
        request_text=data.request_text if data.order_type == "book_delivery" else None,
        order_location=data.order_location if data.order_type == "certificate" else None,
        department=data.department if data.order_type == "certificate" else None,
        social_protection_information=(
            data.social_protection_information if data.order_type == "certificate" else None
        ),
        study_form=data.study_form if data.order_type == "certificate" else None,
        group_name=group_name,
        certificate_type=data.certificate_type if data.order_type == "certificate" else None,
        scholarship_payment_period=(
            data.scholarship_payment_period if data.order_type == "certificate" else None
        ),
        custom_scholarship_payment_period=(
            data.custom_scholarship_payment_period if data.order_type == "certificate" else None
        ),
        place_of_requirement=(
            data.place_of_requirement if data.order_type == "certificate" else None
        ),
        copies_count=data.copies_count if data.order_type == "certificate" else None,
        status="new",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@router.get(
    "/me",
    response_model=list[DocumentOrderOut],
    dependencies=[Depends(require_role_any(["student"]))],
)
async def my_document_orders(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    student = _student_for_user(db, user)
    return db.scalars(
        select(DocumentOrder)
        .where(DocumentOrder.student_id == student.id)
        .order_by(DocumentOrder.created_at.desc())
    ).all()


@router.get(
    "",
    response_model=list[DocumentOrderOut],
    dependencies=[Depends(require_role_any(["administrator", "director"]))],
)
async def list_all_orders(
    db: Session = Depends(get_db),
    order_type: Optional[OrderType] = Query(None),
    status: Optional[OrderStatus] = Query(None),
    created_from: date | None = Query(None),
    created_to: date | None = Query(None),
    group_name: str | None = Query(None),
    student_id: int | None = Query(None),
    q: str | None = Query(None, max_length=200),
):
    statement = _filtered_orders_statement(
        order_type=order_type,
        status=status,
        created_from=created_from,
        created_to=created_to,
        group_name=group_name,
        student_id=student_id,
        q=q,
    )
    return db.scalars(statement).all()


@router.get(
    "/export",
    dependencies=[Depends(require_admin)],
)
async def export_book_orders(
    db: Session = Depends(get_db),
    status: Optional[OrderStatus] = Query(None),
    created_from: date | None = Query(None),
    created_to: date | None = Query(None),
    group_name: str | None = Query(None),
    student_id: int | None = Query(None),
    q: str | None = Query(None, max_length=200),
):
    statement = _filtered_orders_statement(
        order_type="book_delivery",
        status=status,
        created_from=created_from,
        created_to=created_to,
        group_name=group_name,
        student_id=student_id,
        q=q,
    )
    return _book_export_response(list(db.scalars(statement).all()))


@router.post(
    "/export-links",
    response_model=DocumentOrderExportLinkOut,
    dependencies=[Depends(require_admin)],
)
async def create_book_export_link(
    data: DocumentOrderExportLinkCreate,
    request: Request,
    user: User = Depends(get_current_user),
):
    filters = data.model_dump(
        mode="json",
        exclude={"expires_in_hours"},
        exclude_none=True,
    )
    token, expires_at = create_export_link_token(
        filters=filters,
        creator_id=user.id,
        expires_in_hours=data.expires_in_hours,
    )
    return {
        "url": str(
            request.url_for(
                "download_public_document_orders_export",
                token=token,
            )
        ),
        "expires_at": expires_at,
    }


@router.get("/public-export/{token}", name="download_public_document_orders_export")
async def download_public_document_orders_export(
    token: str,
    db: Session = Depends(get_db),
):
    try:
        payload = decode_export_link_token(token)
        raw_filters = payload["filters"]
        created_from = date.fromisoformat(raw_filters["created_from"]) if raw_filters.get("created_from") else None
        created_to = date.fromisoformat(raw_filters["created_to"]) if raw_filters.get("created_to") else None
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=404,
            detail="Ссылка на выгрузку недействительна или истекла",
        ) from exc

    statement = _filtered_orders_statement(
        order_type="book_delivery",
        status=raw_filters.get("status"),
        created_from=created_from,
        created_to=created_to,
        group_name=raw_filters.get("group_name"),
        student_id=raw_filters.get("student_id"),
        q=raw_filters.get("q"),
    )
    return _book_export_response(list(db.scalars(statement).all()))


@router.patch(
    "/{order_id}",
    response_model=DocumentOrderOut,
    dependencies=[Depends(require_role_any(["administrator", "director"]))],
)
async def update_order(
    order_id: int,
    data: DocumentOrderUpdate = Body(...),
    db: Session = Depends(get_db),
):
    order = db.get(DocumentOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Заявка на документ не найдена")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(order, field, value)
    db.commit()
    db.refresh(order)
    return order


@router.post(
    "/{order_id}/confirm-receipt",
    response_model=DocumentOrderOut,
    dependencies=[Depends(require_role_any(["student"]))],
)
async def confirm_order_receipt(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    student = _student_for_user(db, user)
    order = db.get(DocumentOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Заявка на документ не найдена")
    if order.student_id != student.id:
        raise HTTPException(status_code=403, detail="Нельзя подтвердить получение чужой заявки")
    if order.status != "ready":
        raise HTTPException(
            status_code=400,
            detail="Подтвердить получение можно только для готовой заявки",
        )
    order.status = "student_approved"
    db.commit()
    db.refresh(order)
    return order


@router.delete(
    "/{order_id}",
    dependencies=[Depends(require_role_any(["student", "administrator", "director"]))],
)
async def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.get(DocumentOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Заявка на документ не найдена")

    roles = _role_names(db, user.id)
    is_staff = bool(roles.intersection({"administrator", "director"}))
    if not is_staff:
        student = _student_for_user(db, user)
        if order.student_id != student.id:
            raise HTTPException(status_code=403, detail="Нельзя удалить заявку другого студента")
        if order.status != "new":
            raise HTTPException(status_code=403, detail="Можно удалить только новую заявку")

    if order.result_file:
        absolute_path = os.path.join(settings.MEDIA_ROOT, order.result_file)
        if os.path.isfile(absolute_path):
            try:
                os.remove(absolute_path)
            except OSError:
                pass

    db.delete(order)
    db.commit()
    return {"status": "deleted", "id": order_id}
