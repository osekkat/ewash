"""booking confirmation notification settings

Revision ID: 20260505_0004
Revises: 20260505_0003
Create Date: 2026-05-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260505_0004"
down_revision = "20260505_0003"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if "booking_notification_settings" not in _tables():
        op.create_table(
            "booking_notification_settings",
            sa.Column("settings_key", sa.String(length=40), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("phone_number", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("template_name", sa.String(length=160), nullable=False, server_default=""),
            sa.Column("template_language", sa.String(length=16), nullable=False, server_default="fr"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    if "ix_booking_notification_settings_enabled" not in _indexes("booking_notification_settings"):
        op.create_index("ix_booking_notification_settings_enabled", "booking_notification_settings", ["enabled"])


def downgrade() -> None:
    if "booking_notification_settings" in _tables():
        op.drop_table("booking_notification_settings")
