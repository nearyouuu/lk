from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


OrderLocation = Literal["ivanovo_medical_college", "shuya_branch"]
Department = Literal["paramedic", "nursing", "pharmacy", "paid_services"]
SocialProtectionInformation = Literal[
    "nursing_9_full_time_first",
    "nursing_11_full_time_first",
    "general_medicine_9_full_time_first",
    "general_medicine_11_full_time_first",
]
StudyForm = Literal["full_time", "part_time_evening"]
CertificateType = Literal["education", "scholarship_payment"]
ScholarshipPaymentPeriod = Literal["3_months", "6_months", "1_year", "custom"]
OrderStatus = Literal["new", "in_progress", "ready", "rejected", "student_approved"]
OrderType = Literal["certificate", "book_delivery"]


ENUM_VALUES = {
    "order_location": {"ivanovo_medical_college", "shuya_branch"},
    "department": {"paramedic", "nursing", "pharmacy", "paid_services"},
    "social_protection_information": {
        "nursing_9_full_time_first",
        "nursing_11_full_time_first",
        "general_medicine_9_full_time_first",
        "general_medicine_11_full_time_first",
    },
    "study_form": {"full_time", "part_time_evening"},
    "certificate_type": {"education", "scholarship_payment"},
    "scholarship_payment_period": {"3_months", "6_months", "1_year", "custom"},
    "status": {"new", "in_progress", "ready", "rejected", "student_approved"},
    "order_type": {"certificate", "book_delivery"},
}


class DocumentOrderCreate(BaseModel):
    order_type: OrderType = "certificate"
    request_text: str | None = None
    full_name: str | None = None
    order_location: OrderLocation | None = None
    department: Department | None = None
    social_protection_information: SocialProtectionInformation | None = None
    study_form: StudyForm | None = None
    group_name: str | None = None
    certificate_type: CertificateType | None = None
    scholarship_payment_period: ScholarshipPaymentPeriod | None = None
    custom_scholarship_payment_period: str | None = None
    place_of_requirement: str | None = None
    copies_count: int | None = Field(default=None, strict=True)

    @field_validator(
        "full_name",
        "request_text",
        "order_location",
        "department",
        "social_protection_information",
        "study_form",
        "group_name",
        "certificate_type",
        "scholarship_payment_period",
        "custom_scholarship_payment_period",
        "place_of_requirement",
        mode="before",
    )
    @classmethod
    def trim_strings(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("full_name", "group_name", "place_of_requirement")
    @classmethod
    def required_string_not_empty(cls, value: str | None) -> str | None:
        if value is not None and not value:
            raise ValueError("Поле не может быть пустым")
        return value

    @field_validator(
        "order_location",
        "department",
        "social_protection_information",
        "study_form",
        "certificate_type",
        "scholarship_payment_period",
        "order_type",
        mode="before",
    )
    @classmethod
    def validate_enum_values(cls, value, info):
        if value is None and info.field_name in {
            "order_location",
            "department",
            "social_protection_information",
            "study_form",
            "certificate_type",
            "scholarship_payment_period",
        }:
            return value
        normalized = value.strip() if isinstance(value, str) else value
        if not isinstance(normalized, str) or normalized not in ENUM_VALUES[info.field_name]:
            raise ValueError(f"Недопустимое значение поля {info.field_name}")
        return normalized

    @field_validator("copies_count")
    @classmethod
    def validate_copies_count(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if not 1 <= value <= 10:
            raise ValueError("Количество экземпляров должно быть от 1 до 10")
        return value

    @model_validator(mode="after")
    def validate_scholarship_period(self):
        if self.order_type == "book_delivery":
            if not self.request_text:
                raise ValueError("Текст заявки на книгу не может быть пустым")
            if len(self.request_text) > 2000:
                raise ValueError("Текст заявки на книгу не должен превышать 2000 символов")
            return self

        required_fields = (
            "full_name",
            "order_location",
            "department",
            "social_protection_information",
            "study_form",
            "group_name",
            "certificate_type",
            "place_of_requirement",
            "copies_count",
        )
        for field_name in required_fields:
            if getattr(self, field_name) is None:
                raise ValueError(f"Обязательное поле не заполнено: {field_name}")
        if self.request_text is not None:
            raise ValueError("Текст заявки на книгу должен быть null для заявки на документ")

        if self.certificate_type == "education":
            if self.scholarship_payment_period is not None:
                raise ValueError("Для справки об обучении период выплаты должен быть null")
            if self.custom_scholarship_payment_period is not None:
                raise ValueError("Для справки об обучении произвольный период должен быть null")
            return self

        if self.scholarship_payment_period is None:
            raise ValueError("Для справки о выплате стипендии необходимо указать период")
        if self.scholarship_payment_period == "custom":
            if not self.custom_scholarship_payment_period:
                raise ValueError("Для произвольного периода необходимо указать его значение")
        elif self.custom_scholarship_payment_period is not None:
            raise ValueError("Произвольный период должен быть null для выбранного периода выплаты")
        return self


class DocumentOrderUpdate(BaseModel):
    status: OrderStatus | None = None
    comment_admin: str | None = None

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value):
        if value is None:
            return value
        normalized = value.strip() if isinstance(value, str) else value
        if not isinstance(normalized, str) or normalized not in ENUM_VALUES["status"]:
            raise ValueError("Недопустимое значение поля status")
        return normalized

    @field_validator("comment_admin", mode="before")
    @classmethod
    def trim_comment(cls, value):
        return value.strip() if isinstance(value, str) else value


class DocumentOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    full_name: str
    order_type: OrderType
    request_text: str | None
    order_location: OrderLocation | None
    department: Department | None
    social_protection_information: SocialProtectionInformation | None
    study_form: StudyForm | None
    group_name: str
    certificate_type: CertificateType | None
    scholarship_payment_period: ScholarshipPaymentPeriod | None
    custom_scholarship_payment_period: str | None
    place_of_requirement: str | None
    copies_count: int | None
    status: OrderStatus
    comment_admin: str | None
    result_file: str | None
    created_at: datetime
    updated_at: datetime


class BookOrderFilters(BaseModel):
    status: OrderStatus | None = None
    created_from: date | None = None
    created_to: date | None = None
    group_name: str | None = None
    student_id: int | None = Field(default=None, ge=1)
    q: str | None = Field(default=None, max_length=200)

    @field_validator("group_name", "q", mode="before")
    @classmethod
    def trim_filter_strings(cls, value):
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @model_validator(mode="after")
    def validate_period(self):
        if self.created_from and self.created_to and self.created_from > self.created_to:
            raise ValueError("Дата начала периода не может быть позже даты окончания")
        return self


class DocumentOrderExportLinkCreate(BookOrderFilters):
    expires_in_hours: int = Field(default=168, ge=1, le=168)


class DocumentOrderExportLinkOut(BaseModel):
    url: str
    expires_at: datetime
