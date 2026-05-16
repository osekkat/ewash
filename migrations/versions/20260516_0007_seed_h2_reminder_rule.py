"""seed default H-2 reminder rule

Revision ID: 20260516_0007
Revises: 20260514_0006
Create Date: 2026-05-16

A fresh deployment has no ``ReminderRuleRow`` rows, so
``persistence._h2_reminder_rule()`` returns ``None`` and
``_create_h2_reminder_for_confirmed_booking`` writes a ``BookingReminderRow``
with ``rule_id = NULL``. The H-2 dispatcher then falls back to the hard-coded
``booking_reminder_h2`` template name; admins who haven't visited
``/admin/reminders`` cannot see, edit, or pause that cadence.

Seed one row matching the dispatcher's lookup so the rule shows up in
``/admin/reminders`` from day one and the cadence is admin-editable.

Idempotent via ``INSERT ... SELECT ... WHERE NOT EXISTS`` so a rerun
(downgrade + upgrade, or repeated ``alembic upgrade head`` cycles) does not
duplicate the seed. ``reminder_rules.name`` is intentionally not unique —
admins can configure multiple cadences with the same human-facing label —
so we cannot rely on ``ON CONFLICT (name) DO NOTHING``.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260516_0007"
down_revision = "20260514_0006"
branch_labels = None
depends_on = None


SEED_NAME = "H-2"
SEED_OFFSET_MINUTES = 120
SEED_TEMPLATE = "booking_reminder_h2"
SEED_CHANNEL = "whatsapp_template"


def _is_offline() -> bool:
    return bool(op.get_context().as_sql)


def _tables() -> set[str]:
    if _is_offline():
        return set()
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _is_offline():
        return
    if "reminder_rules" not in _tables():
        # Defensive: production calls init_db() (Base.metadata.create_all) at
        # startup before any alembic-driven step, so reminder_rules exists by
        # the time this migration runs. Downgrade/redo cycles or alembic-only
        # invocations on an empty schema may still hit this branch — skip
        # rather than crash.
        return

    op.execute(
        sa.text(
            "INSERT INTO reminder_rules "
            "(name, enabled, offset_minutes_before, max_sends, "
            "min_minutes_between_sends, template_name, channel) "
            "SELECT :name, :enabled, :offset_minutes, :max_sends, "
            ":min_minutes, :template, :channel "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM reminder_rules WHERE name = :name"
            ")"
        ).bindparams(
            name=SEED_NAME,
            enabled=True,
            offset_minutes=SEED_OFFSET_MINUTES,
            max_sends=1,
            min_minutes=0,
            template=SEED_TEMPLATE,
            channel=SEED_CHANNEL,
        )
    )


def downgrade() -> None:
    if _is_offline():
        return
    if "reminder_rules" not in _tables():
        return

    op.execute(
        sa.text(
            "DELETE FROM reminder_rules "
            "WHERE name = :name "
            "AND offset_minutes_before = :offset_minutes "
            "AND template_name = :template "
            "AND channel = :channel"
        ).bindparams(
            name=SEED_NAME,
            offset_minutes=SEED_OFFSET_MINUTES,
            template=SEED_TEMPLATE,
            channel=SEED_CHANNEL,
        )
    )
