"""operational schema foundations

Revision ID: 20260505_0001
Revises:
Create Date: 2026-05-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.models import Base

revision = "20260505_0001"
down_revision = None
branch_labels = None
depends_on = None


BOOKING_STATUSES = (
    "draft",
    "awaiting_confirmation",
    "pending_ewash_confirmation",
    "confirmed",
    "rescheduled",
    "customer_cancelled",
    "admin_cancelled",
    "expired",
    "no_show",
    "technician_en_route",
    "arrived",
    "in_progress",
    "completed",
    "completed_with_issue",
    "refunded",
)


def _is_offline() -> bool:
    return bool(op.get_context().as_sql)


def _tables() -> set[str]:
    if _is_offline():
        return set()
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    if _is_offline():
        return set()
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if table in _tables() and column.name not in _columns(table):
        op.add_column(table, column)


def _seed_services() -> None:
    if "services" not in _tables():
        return
    bind = op.get_bind()
    rows = [
        ("svc_ext", "L'Extérieur", "Carrosserie, vitres, jantes + wax 1 semaine", "wash", "car", 0),
        ("svc_cpl", "Le Complet", "L'Extérieur + intérieur + aspirateur tapis/sièges", "wash", "car", 1),
        ("svc_sal", "Le Salon", "Le Complet + injection/extraction sièges & tissus", "wash", "car", 2),
        ("svc_pol", "Le Polissage", "Rénov. carrosserie + protection hydrophobe 4 sem.", "detailing", "car", 3),
        ("svc_cer6m", "Céramique 6m", "Protection céramique longue durée (6 mois)", "detailing", "car", 4),
        ("svc_cer6w", "Céramique 6s", "Protection céramique express (6 semaines)", "detailing", "car", 5),
        ("svc_cuir", "Rénov. Cuir", "Nettoyage & nourrissage des sièges et garnitures cuir", "detailing", "car", 6),
        ("svc_plastq", "Rénov. Plast.", "Rénovation & protection plastiques (6 mois)", "detailing", "car", 7),
        ("svc_optq", "Rénov. Optiques", "Ponçage + polissage des optiques de phares", "detailing", "car", 8),
        ("svc_lustre", "Lustrage", "Lustrage carrosserie (sans polissage)", "detailing", "car", 9),
        ("svc_scooter", "Scooter", "Lavage complet scooter 2 roues", "wash", "moto", 10),
        ("svc_moto", "Moto", "Lavage complet moto", "wash", "moto", 11),
    ]
    for service_id, name, description, bucket, vehicle_lane, sort_order in rows:
        existing = bind.execute(
            sa.text("SELECT 1 FROM services WHERE service_id = :service_id"),
            {"service_id": service_id},
        ).first()
        if existing is not None:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO services (
                    service_id,
                    name,
                    description,
                    bucket,
                    vehicle_lane,
                    active,
                    sort_order
                )
                VALUES (
                    :service_id,
                    :name,
                    :description,
                    :bucket,
                    :vehicle_lane,
                    :active,
                    :sort_order
                )
                """
            ),
            {
                "service_id": service_id,
                "name": name,
                "description": description,
                "bucket": bucket,
                "vehicle_lane": vehicle_lane,
                "active": True,
                "sort_order": sort_order,
            },
        )


def upgrade() -> None:
    if _is_offline():
        Base.metadata.create_all(bind=op.get_bind(), checkfirst=False)
        return

    tables = _tables()
    if "customers" not in tables or "bookings" not in tables:
        Base.metadata.create_all(bind=op.get_bind())
        _seed_services()
        return

    if "services" not in tables:
        op.create_table(
            "services",
            sa.Column("service_id", sa.String(length=40), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("description", sa.String(length=240), nullable=False, server_default=""),
            sa.Column("bucket", sa.String(length=40), nullable=False, server_default=""),
            sa.Column("vehicle_lane", sa.String(length=40), nullable=False, server_default="car"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_services_active", "services", ["active"])
        op.create_index("ix_services_bucket", "services", ["bucket"])
        op.create_index("ix_services_sort_order", "services", ["sort_order"])
        op.create_index("ix_services_vehicle_lane", "services", ["vehicle_lane"])
    _seed_services()

    if "booking_ref_counters" not in tables:
        op.create_table(
            "booking_ref_counters",
            sa.Column("year", sa.Integer(), primary_key=True),
            sa.Column("last_counter", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    _add_column_if_missing("bookings", sa.Column("center_id", sa.String(length=40), nullable=False, server_default=""))
    _add_column_if_missing("bookings", sa.Column("address_text", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("bookings", sa.Column("location_name", sa.String(length=160), nullable=False, server_default=""))
    _add_column_if_missing("bookings", sa.Column("location_address", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("bookings", sa.Column("latitude", sa.Float(), nullable=True))
    _add_column_if_missing("bookings", sa.Column("longitude", sa.Float(), nullable=True))
    _add_column_if_missing("bookings", sa.Column("appointment_date", sa.Date(), nullable=True))
    _add_column_if_missing("bookings", sa.Column("slot_id", sa.String(length=40), nullable=False, server_default=""))
    _add_column_if_missing("bookings", sa.Column("total_price_dh", sa.Integer(), nullable=False, server_default="0"))

    tables = _tables()
    if "booking_line_items" not in tables:
        op.create_table(
            "booking_line_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id"), nullable=False),
            sa.Column("kind", sa.String(length=40), nullable=False, server_default="main"),
            sa.Column("service_id", sa.String(length=40), sa.ForeignKey("services.service_id"), nullable=False),
            sa.Column("service_bucket", sa.String(length=40), nullable=False, server_default=""),
            sa.Column("label_snapshot", sa.String(length=180), nullable=False, server_default=""),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("unit_price_dh", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("regular_price_dh", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_price_dh", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("discount_label", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("quantity > 0", name="ck_booking_line_items_quantity_positive"),
            sa.CheckConstraint("unit_price_dh >= 0", name="ck_booking_line_items_unit_price_nonnegative"),
            sa.CheckConstraint("regular_price_dh >= 0", name="ck_booking_line_items_regular_price_nonnegative"),
            sa.CheckConstraint("total_price_dh >= 0", name="ck_booking_line_items_total_price_nonnegative"),
        )
        op.create_index("ix_booking_line_items_booking_id", "booking_line_items", ["booking_id"])
        op.create_index("ix_booking_line_items_booking_kind", "booking_line_items", ["booking_id", "kind"])
        op.create_index("ix_booking_line_items_kind", "booking_line_items", ["kind"])
        op.create_index("ix_booking_line_items_service_id", "booking_line_items", ["service_id"])
        op.create_index("ix_booking_line_items_sort_order", "booking_line_items", ["sort_order"])

    if "whatsapp_messages" not in tables:
        op.create_table(
            "whatsapp_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("message_id", sa.String(length=160), nullable=False, server_default=""),
            sa.Column("phone", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("direction", sa.String(length=16), nullable=False, server_default="inbound"),
            sa.Column("message_type", sa.String(length=40), nullable=False, server_default=""),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="received"),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("direction IN ('inbound','outbound')", name="ck_whatsapp_messages_direction"),
            sa.UniqueConstraint("message_id", name="uq_whatsapp_messages_message_id"),
        )
        op.create_index("ix_whatsapp_messages_direction", "whatsapp_messages", ["direction"])
        op.create_index("ix_whatsapp_messages_message_id", "whatsapp_messages", ["message_id"])
        op.create_index("ix_whatsapp_messages_phone", "whatsapp_messages", ["phone"])
        op.create_index("ix_whatsapp_messages_status", "whatsapp_messages", ["status"])

    if "conversation_sessions" not in tables:
        op.create_table(
            "conversation_sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("customer_phone", sa.String(length=32), sa.ForeignKey("customers.phone"), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_event_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("current_stage", sa.String(length=60), nullable=False, server_default=""),
        )
        op.create_index("ix_conversation_sessions_customer_phone", "conversation_sessions", ["customer_phone"])
        op.create_index("ix_conversation_sessions_current_stage", "conversation_sessions", ["current_stage"])
        op.create_index("ix_conversation_sessions_phone_status", "conversation_sessions", ["customer_phone", "status"])
        op.create_index("ix_conversation_sessions_status", "conversation_sessions", ["status"])

    if "conversation_events" not in tables:
        op.create_table(
            "conversation_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("conversation_sessions.id"), nullable=False),
            sa.Column("customer_phone", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("stage", sa.String(length=60), nullable=False, server_default=""),
            sa.Column("stage_label", sa.String(length=160), nullable=False, server_default=""),
            sa.Column("event_type", sa.String(length=60), nullable=False, server_default="stage_seen"),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_conversation_events_customer_phone", "conversation_events", ["customer_phone"])
        op.create_index("ix_conversation_events_event_type", "conversation_events", ["event_type"])
        op.create_index("ix_conversation_events_session_id", "conversation_events", ["session_id"])
        op.create_index("ix_conversation_events_stage", "conversation_events", ["stage"])

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        existing_uniques = {item["name"] for item in inspect(bind).get_unique_constraints("bookings")}
        if "uq_bookings_ref" not in existing_uniques:
            op.create_unique_constraint("uq_bookings_ref", "bookings", ["ref"])


def downgrade() -> None:
    for table in (
        "conversation_events",
        "conversation_sessions",
        "whatsapp_messages",
        "booking_line_items",
        "booking_ref_counters",
    ):
        if table in _tables():
            op.drop_table(table)

    for column in (
        "total_price_dh",
        "slot_id",
        "appointment_date",
        "longitude",
        "latitude",
        "location_address",
        "location_name",
        "address_text",
        "center_id",
    ):
        if "bookings" in _tables() and column in _columns("bookings"):
            op.drop_column("bookings", column)
