"""repair operational schema constraints and indexes

Revision ID: 20260505_0003
Revises: 20260505_0002
Create Date: 2026-05-05
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "20260505_0003"
down_revision = "20260505_0002"
branch_labels = None
depends_on = None


BOOKING_STATUS_CHECK = (
    "status IN ('draft','awaiting_confirmation','pending_ewash_confirmation',"
    "'confirmed','rescheduled','customer_cancelled','admin_cancelled','expired',"
    "'no_show','technician_en_route','arrived','in_progress','completed',"
    "'completed_with_issue','refunded')"
)


def _is_offline() -> bool:
    return bool(op.get_context().as_sql)


def _inspector():
    return inspect(op.get_bind())


def _tables() -> set[str]:
    if _is_offline():
        return set()
    return set(_inspector().get_table_names())


def _columns(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {column["name"] for column in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {index["name"] for index in _inspector().get_indexes(table)}


def _uniques(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {constraint["name"] for constraint in _inspector().get_unique_constraints(table)}


def _checks(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {constraint["name"] for constraint in _inspector().get_check_constraints(table)}


def _create_index_if_missing(table: str, name: str, columns: list[str]) -> None:
    if table in _tables() and set(columns).issubset(_columns(table)) and name not in _indexes(table):
        op.create_index(name, table, columns)


def upgrade() -> None:
    if _is_offline():
        return

    bind = op.get_bind()

    _create_index_if_missing("bookings", "ix_bookings_center_id", ["center_id"])
    _create_index_if_missing("bookings", "ix_bookings_appointment_date", ["appointment_date"])
    _create_index_if_missing("bookings", "ix_bookings_slot_id", ["slot_id"])
    _create_index_if_missing("customers", "ix_customers_whatsapp_wa_id", ["whatsapp_wa_id"])

    if bind.dialect.name == "sqlite" or "bookings" not in _tables():
        return

    if "uq_bookings_ref" not in _uniques("bookings"):
        op.create_unique_constraint("uq_bookings_ref", "bookings", ["ref"])

    existing_checks = _checks("bookings")
    if "ck_bookings_status" not in existing_checks:
        op.create_check_constraint("ck_bookings_status", "bookings", BOOKING_STATUS_CHECK)
    if "ck_bookings_price_nonnegative" not in existing_checks:
        op.create_check_constraint("ck_bookings_price_nonnegative", "bookings", "price_dh >= 0")
    if "ck_bookings_regular_price_nonnegative" not in existing_checks:
        op.create_check_constraint(
            "ck_bookings_regular_price_nonnegative",
            "bookings",
            "price_regular_dh >= 0",
        )
    if "ck_bookings_addon_price_nonnegative" not in existing_checks:
        op.create_check_constraint(
            "ck_bookings_addon_price_nonnegative",
            "bookings",
            "addon_price_dh >= 0",
        )


def downgrade() -> None:
    if _is_offline():
        return

    bind = op.get_bind()

    for table, index_name in (
        ("customers", "ix_customers_whatsapp_wa_id"),
        ("bookings", "ix_bookings_slot_id"),
        ("bookings", "ix_bookings_appointment_date"),
        ("bookings", "ix_bookings_center_id"),
    ):
        if table in _tables() and index_name in _indexes(table):
            op.drop_index(index_name, table_name=table)

    if bind.dialect.name == "sqlite" or "bookings" not in _tables():
        return

    for constraint_name in (
        "ck_bookings_addon_price_nonnegative",
        "ck_bookings_regular_price_nonnegative",
        "ck_bookings_price_nonnegative",
        "ck_bookings_status",
    ):
        if constraint_name in _checks("bookings"):
            op.drop_constraint(constraint_name, "bookings", type_="check")

    if "uq_bookings_ref" in _uniques("bookings"):
        op.drop_constraint("uq_bookings_ref", "bookings", type_="unique")
