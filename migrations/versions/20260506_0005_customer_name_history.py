"""customer name history

Revision ID: 20260506_0005
Revises: 20260505_0004
Create Date: 2026-05-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260506_0005"
down_revision = "20260505_0004"
branch_labels = None
depends_on = None


def _is_offline() -> bool:
    return bool(op.get_context().as_sql)


def _tables() -> set[str]:
    if _is_offline():
        return set()
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if _is_offline():
        return

    if "customer_names" not in _tables():
        op.create_table(
            "customer_names",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("customer_phone", sa.String(length=32), sa.ForeignKey("customers.phone"), nullable=False),
            sa.Column("display_name", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("normalized_name", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("first_used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("customer_phone", "normalized_name", name="uq_customer_names_phone_normalized"),
        )
    if "ix_customer_names_customer_phone" not in _indexes("customer_names"):
        op.create_index("ix_customer_names_customer_phone", "customer_names", ["customer_phone"])
    if "ix_customer_names_normalized_name" not in _indexes("customer_names"):
        op.create_index("ix_customer_names_normalized_name", "customer_names", ["normalized_name"])
    if "ix_customer_names_last_used_at" not in _indexes("customer_names"):
        op.create_index("ix_customer_names_last_used_at", "customer_names", ["last_used_at"])


def downgrade() -> None:
    if _is_offline():
        return

    if "customer_names" in _tables():
        op.drop_table("customer_names")
