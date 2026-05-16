"""customer contact capture

Revision ID: 20260505_0002
Revises: 20260505_0001
Create Date: 2026-05-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260505_0002"
down_revision = "20260505_0001"
branch_labels = None
depends_on = None


def _is_offline() -> bool:
    return bool(op.get_context().as_sql)


def _columns(table: str) -> set[str]:
    if _is_offline():
        return set()
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _is_offline():
        return

    columns = _columns("customers")
    if "whatsapp_profile_name" not in columns:
        op.add_column(
            "customers",
            sa.Column("whatsapp_profile_name", sa.String(length=120), nullable=False, server_default=""),
        )
    if "whatsapp_wa_id" not in columns:
        op.add_column(
            "customers",
            sa.Column("whatsapp_wa_id", sa.String(length=32), nullable=False, server_default=""),
        )
        op.create_index("ix_customers_whatsapp_wa_id", "customers", ["whatsapp_wa_id"])


def downgrade() -> None:
    if _is_offline():
        return

    columns = _columns("customers")
    if "whatsapp_wa_id" in columns:
        op.drop_index("ix_customers_whatsapp_wa_id", table_name="customers")
        op.drop_column("customers", "whatsapp_wa_id")
    if "whatsapp_profile_name" in columns:
        op.drop_column("customers", "whatsapp_profile_name")
