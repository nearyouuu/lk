"""Migrate document orders to the v2 frontend contract.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-17
"""

from alembic import op
import sqlalchemy as sa


revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_orders", sa.Column("full_name", sa.String(255), nullable=True))
    op.add_column("document_orders", sa.Column("order_location", sa.String(50), nullable=True))
    op.add_column("document_orders", sa.Column("department", sa.String(50), nullable=True))
    op.add_column(
        "document_orders",
        sa.Column("social_protection_information", sa.String(100), nullable=True),
    )
    op.add_column("document_orders", sa.Column("study_form", sa.String(50), nullable=True))
    op.add_column("document_orders", sa.Column("group_name", sa.String(50), nullable=True))
    op.add_column("document_orders", sa.Column("certificate_type", sa.String(50), nullable=True))
    op.add_column(
        "document_orders",
        sa.Column("scholarship_payment_period", sa.String(50), nullable=True),
    )
    op.add_column(
        "document_orders",
        sa.Column("custom_scholarship_payment_period", sa.Text(), nullable=True),
    )
    op.add_column("document_orders", sa.Column("place_of_requirement", sa.Text(), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE document_orders AS orders
            SET
                full_name = COALESCE(NULLIF(BTRIM(users.full_name), ''), users.email, 'Не указано'),
                order_location = CASE
                    WHEN orders.delivery_method IN ('ivanovo_medical_college', 'shuya_branch')
                        THEN orders.delivery_method
                    ELSE 'ivanovo_medical_college'
                END,
                department = 'paid_services',
                social_protection_information = 'nursing_9_full_time_first',
                study_form = 'full_time',
                group_name = COALESCE(NULLIF(BTRIM(groups.code), ''), 'Не указано'),
                certificate_type = CASE
                    WHEN LOWER(orders.document_type) LIKE '%стипенд%'
                        THEN 'scholarship_payment'
                    ELSE 'education'
                END,
                scholarship_payment_period = CASE
                    WHEN LOWER(orders.document_type) LIKE '%стипенд%' THEN 'custom'
                    ELSE NULL
                END,
                custom_scholarship_payment_period = CASE
                    WHEN LOWER(orders.document_type) LIKE '%стипенд%'
                        THEN 'Период не указан в старой заявке'
                    ELSE NULL
                END,
                place_of_requirement = COALESCE(
                    NULLIF(BTRIM(orders.comment_student), ''),
                    'Не указано (перенесено из старой заявки)'
                )
            FROM students
            JOIN users ON users.id = students.user_id
            LEFT JOIN groups ON groups.id = students.group_id
            WHERE students.id = orders.student_id
            """
        )
    )

    for column_name in (
        "full_name",
        "order_location",
        "department",
        "social_protection_information",
        "study_form",
        "group_name",
        "certificate_type",
        "place_of_requirement",
    ):
        op.alter_column("document_orders", column_name, nullable=False)

    op.execute(
        """
        UPDATE document_orders
        SET copies_count = LEAST(10, GREATEST(1, copies_count))
        """
    )

    constraints = {
        "ck_document_orders_copies_count": "copies_count BETWEEN 1 AND 10",
        "ck_document_orders_order_location": (
            "order_location IN ('ivanovo_medical_college', 'shuya_branch')"
        ),
        "ck_document_orders_department": (
            "department IN ('paramedic', 'nursing', 'pharmacy', 'paid_services')"
        ),
        "ck_document_orders_social_protection_information": (
            "social_protection_information IN "
            "('nursing_9_full_time_first', 'nursing_11_full_time_first', "
            "'general_medicine_9_full_time_first', 'general_medicine_11_full_time_first')"
        ),
        "ck_document_orders_study_form": (
            "study_form IN ('full_time', 'part_time_evening')"
        ),
        "ck_document_orders_certificate_type": (
            "certificate_type IN ('education', 'scholarship_payment')"
        ),
        "ck_document_orders_scholarship_payment_period": (
            "scholarship_payment_period IS NULL OR scholarship_payment_period IN "
            "('3_months', '6_months', '1_year', 'custom')"
        ),
        "ck_document_orders_payment_period_consistency": (
            "(certificate_type = 'education' AND scholarship_payment_period IS NULL "
            "AND custom_scholarship_payment_period IS NULL) OR "
            "(certificate_type = 'scholarship_payment' AND scholarship_payment_period IS NOT NULL "
            "AND ((scholarship_payment_period = 'custom' "
            "AND custom_scholarship_payment_period IS NOT NULL "
            "AND length(trim(custom_scholarship_payment_period)) > 0) OR "
            "(scholarship_payment_period <> 'custom' "
            "AND custom_scholarship_payment_period IS NULL)))"
        ),
    }
    for name, condition in constraints.items():
        op.create_check_constraint(name, "document_orders", condition)

    op.alter_column("document_orders", "status", server_default="new")
    op.drop_column("document_orders", "comment_student")
    op.drop_column("document_orders", "delivery_method")
    op.drop_column("document_orders", "document_type")


def downgrade() -> None:
    op.add_column("document_orders", sa.Column("document_type", sa.String(255), nullable=True))
    op.add_column("document_orders", sa.Column("delivery_method", sa.String(255), nullable=True))
    op.add_column("document_orders", sa.Column("comment_student", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE document_orders
        SET document_type = certificate_type,
            delivery_method = order_location,
            comment_student = place_of_requirement
        """
    )
    op.alter_column("document_orders", "document_type", nullable=False)
    op.alter_column("document_orders", "delivery_method", nullable=False)

    for constraint_name in (
        "ck_document_orders_payment_period_consistency",
        "ck_document_orders_scholarship_payment_period",
        "ck_document_orders_certificate_type",
        "ck_document_orders_study_form",
        "ck_document_orders_social_protection_information",
        "ck_document_orders_department",
        "ck_document_orders_order_location",
        "ck_document_orders_copies_count",
    ):
        op.drop_constraint(constraint_name, "document_orders", type_="check")

    op.alter_column("document_orders", "status", server_default=None)
    for column_name in (
        "place_of_requirement",
        "custom_scholarship_payment_period",
        "scholarship_payment_period",
        "certificate_type",
        "group_name",
        "study_form",
        "social_protection_information",
        "department",
        "order_location",
        "full_name",
    ):
        op.drop_column("document_orders", column_name)
