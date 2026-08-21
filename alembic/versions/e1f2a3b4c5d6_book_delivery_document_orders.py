"""Add book delivery requests to document orders.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-08-17
"""

from alembic import op
import sqlalchemy as sa


revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_orders",
        sa.Column("order_type", sa.String(50), nullable=False, server_default="certificate"),
    )
    op.add_column("document_orders", sa.Column("request_text", sa.Text(), nullable=True))
    op.create_index("ix_document_orders_order_type", "document_orders", ["order_type"])

    for column_name, column_type in (
        ("order_location", sa.String(50)),
        ("department", sa.String(50)),
        ("social_protection_information", sa.String(100)),
        ("study_form", sa.String(50)),
        ("certificate_type", sa.String(50)),
        ("place_of_requirement", sa.Text()),
        ("copies_count", sa.Integer()),
    ):
        op.alter_column(
            "document_orders",
            column_name,
            existing_type=column_type,
            nullable=True,
        )

    op.drop_constraint("ck_document_orders_copies_count", "document_orders", type_="check")
    op.create_check_constraint(
        "ck_document_orders_copies_count",
        "document_orders",
        "copies_count IS NULL OR copies_count BETWEEN 1 AND 10",
    )
    op.create_check_constraint(
        "ck_document_orders_order_type",
        "document_orders",
        "order_type IN ('certificate', 'book_delivery')",
    )
    op.create_check_constraint(
        "ck_document_orders_type_payload",
        "document_orders",
        "(order_type = 'certificate' AND request_text IS NULL AND "
        "order_location IS NOT NULL AND department IS NOT NULL AND "
        "social_protection_information IS NOT NULL AND study_form IS NOT NULL AND "
        "certificate_type IS NOT NULL AND place_of_requirement IS NOT NULL AND "
        "copies_count IS NOT NULL) OR "
        "(order_type = 'book_delivery' AND request_text IS NOT NULL "
        "AND length(trim(request_text)) BETWEEN 1 AND 2000)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM document_orders WHERE order_type = 'book_delivery'")
    op.drop_constraint("ck_document_orders_type_payload", "document_orders", type_="check")
    op.drop_constraint("ck_document_orders_order_type", "document_orders", type_="check")
    op.drop_constraint("ck_document_orders_copies_count", "document_orders", type_="check")
    op.create_check_constraint(
        "ck_document_orders_copies_count",
        "document_orders",
        "copies_count BETWEEN 1 AND 10",
    )

    for column_name, column_type in (
        ("order_location", sa.String(50)),
        ("department", sa.String(50)),
        ("social_protection_information", sa.String(100)),
        ("study_form", sa.String(50)),
        ("certificate_type", sa.String(50)),
        ("place_of_requirement", sa.Text()),
        ("copies_count", sa.Integer()),
    ):
        op.alter_column(
            "document_orders",
            column_name,
            existing_type=column_type,
            nullable=False,
        )

    op.drop_index("ix_document_orders_order_type", table_name="document_orders")
    op.drop_column("document_orders", "request_text")
    op.drop_column("document_orders", "order_type")
