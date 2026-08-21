from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


OrderStatusEnum = Enum(
    "new",
    "in_progress",
    "ready",
    "rejected",
    "student_approved",
    name="document_order_status_enum",
)


class DocumentOrder(Base):
    __tablename__ = "document_orders"
    __table_args__ = (
        CheckConstraint(
            "order_type IN ('certificate', 'book_delivery')",
            name="ck_document_orders_order_type",
        ),
        CheckConstraint(
            "(order_type = 'certificate' AND request_text IS NULL AND "
            "order_location IS NOT NULL AND department IS NOT NULL AND "
            "social_protection_information IS NOT NULL AND study_form IS NOT NULL AND "
            "certificate_type IS NOT NULL AND place_of_requirement IS NOT NULL AND "
            "copies_count IS NOT NULL) OR "
            "(order_type = 'book_delivery' AND request_text IS NOT NULL "
            "AND length(trim(request_text)) BETWEEN 1 AND 2000)",
            name="ck_document_orders_type_payload",
        ),
        CheckConstraint(
            "copies_count IS NULL OR copies_count BETWEEN 1 AND 10",
            name="ck_document_orders_copies_count",
        ),
        CheckConstraint(
            "order_location IN ('ivanovo_medical_college', 'shuya_branch')",
            name="ck_document_orders_order_location",
        ),
        CheckConstraint(
            "department IN ('paramedic', 'nursing', 'pharmacy', 'paid_services')",
            name="ck_document_orders_department",
        ),
        CheckConstraint(
            "social_protection_information IN "
            "('nursing_9_full_time_first', 'nursing_11_full_time_first', "
            "'general_medicine_9_full_time_first', 'general_medicine_11_full_time_first')",
            name="ck_document_orders_social_protection_information",
        ),
        CheckConstraint(
            "study_form IN ('full_time', 'part_time_evening')",
            name="ck_document_orders_study_form",
        ),
        CheckConstraint(
            "certificate_type IN ('education', 'scholarship_payment')",
            name="ck_document_orders_certificate_type",
        ),
        CheckConstraint(
            "scholarship_payment_period IS NULL OR scholarship_payment_period IN "
            "('3_months', '6_months', '1_year', 'custom')",
            name="ck_document_orders_scholarship_payment_period",
        ),
        CheckConstraint(
            "(certificate_type = 'education' AND scholarship_payment_period IS NULL "
            "AND custom_scholarship_payment_period IS NULL) OR "
            "(certificate_type = 'scholarship_payment' AND scholarship_payment_period IS NOT NULL "
            "AND ((scholarship_payment_period = 'custom' "
            "AND custom_scholarship_payment_period IS NOT NULL "
            "AND length(trim(custom_scholarship_payment_period)) > 0) OR "
            "(scholarship_payment_period <> 'custom' "
            "AND custom_scholarship_payment_period IS NULL)))",
            name="ck_document_orders_payment_period_consistency",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(255))
    order_type: Mapped[str] = mapped_column(String(50), default="certificate", index=True)
    request_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_location: Mapped[str | None] = mapped_column(String(50), nullable=True)
    department: Mapped[str | None] = mapped_column(String(50), nullable=True)
    social_protection_information: Mapped[str | None] = mapped_column(String(100), nullable=True)
    study_form: Mapped[str | None] = mapped_column(String(50), nullable=True)
    group_name: Mapped[str] = mapped_column(String(50))
    certificate_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scholarship_payment_period: Mapped[str | None] = mapped_column(String(50), nullable=True)
    custom_scholarship_payment_period: Mapped[str | None] = mapped_column(Text, nullable=True)
    place_of_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    copies_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(OrderStatusEnum, default="new")
    comment_admin: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    student = relationship("Student", back_populates="document_orders")
