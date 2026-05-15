import os
import tempfile
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, select, text

from app.db import init_db, make_engine, normalize_database_url, session_scope
from app.models import (
    AdminTextRow,
    BookingReminderRow,
    BookingLineItemRow,
    BookingRefCounterRow,
    BookingRow,
    BookingStatusEventRow,
    CenterRow,
    ClosedDateRow,
    ConversationEventRow,
    ConversationSessionRow,
    Customer,
    CustomerName,
    CustomerTokenRow,
    CustomerVehicle,
    DataErasureAuditRow,
    PromoCodeRow,
    PromoDiscountRow,
    ReminderRuleRow,
    ServiceRow,
    ServicePriceRow,
    TimeSlotRow,
    VehicleColor,
    VehicleModel,
    WhatsappMessageRow,
)


def test_normalize_database_url_supports_railway_postgres_scheme():
    assert normalize_database_url("postgres://user:pass@host:5432/db") == (
        "postgresql+psycopg://user:pass@host:5432/db"
    )
    assert normalize_database_url("postgresql://user:pass@host:5432/db") == (
        "postgresql+psycopg://user:pass@host:5432/db"
    )
    assert normalize_database_url("postgresql+psycopg://user:pass@host:5432/db") == (
        "postgresql+psycopg://user:pass@host:5432/db"
    )
    assert normalize_database_url("sqlite+pysqlite:///:memory:") == "sqlite+pysqlite:///:memory:"


def test_init_db_creates_v03_core_tables():
    engine = make_engine("sqlite+pysqlite:///:memory:")

    init_db(engine)

    tables = set(inspect(engine).get_table_names())
    assert {
        "customers",
        "customer_names",
        "customer_vehicles",
        "vehicle_models",
        "vehicle_colors",
        "bookings",
        "booking_line_items",
        "booking_ref_counters",
        "booking_status_events",
        "conversation_sessions",
        "conversation_events",
        "reminder_rules",
        "booking_reminders",
        "services",
        "service_prices",
        "promo_codes",
        "promo_discounts",
        "whatsapp_messages",
        "closed_dates",
        "time_slots",
        "centers",
        "admin_texts",
        "booking_notification_settings",
    }.issubset(tables)
    booking_uniques = {tuple(item["column_names"]) for item in inspect(engine).get_unique_constraints("bookings")}
    assert ("ref",) in booking_uniques
    booking_columns = {column["name"] for column in inspect(engine).get_columns("bookings")}
    assert {
        "appointment_date",
        "slot_id",
        "center_id",
        "address_text",
        "latitude",
        "longitude",
        "total_price_dh",
    }.issubset(booking_columns)
    service_columns = {column["name"] for column in inspect(engine).get_columns("services")}
    assert {"service_id", "name", "bucket", "vehicle_lane", "active", "sort_order"}.issubset(service_columns)
    line_item_columns = {column["name"] for column in inspect(engine).get_columns("booking_line_items")}
    assert {"booking_id", "kind", "service_id", "unit_price_dh", "total_price_dh"}.issubset(line_item_columns)
    whatsapp_columns = {column["name"] for column in inspect(engine).get_columns("whatsapp_messages")}
    assert {"message_id", "phone", "direction", "payload_json", "processed_at"}.issubset(whatsapp_columns)
    conversation_columns = {column["name"] for column in inspect(engine).get_columns("conversation_events")}
    assert {"session_id", "customer_phone", "stage", "stage_label", "event_type"}.issubset(conversation_columns)
    customer_columns = {column["name"] for column in inspect(engine).get_columns("customers")}
    assert {"whatsapp_profile_name", "whatsapp_wa_id"}.issubset(customer_columns)
    customer_name_columns = {column["name"] for column in inspect(engine).get_columns("customer_names")}
    assert {"customer_phone", "display_name", "normalized_name", "last_used_at"}.issubset(customer_name_columns)
    vehicle_columns = {column["name"] for column in inspect(engine).get_columns("customer_vehicles")}
    assert {"model_id", "color_id"}.issubset(vehicle_columns)
    service_price_columns = {column["name"] for column in inspect(engine).get_columns("service_prices")}
    assert {"service_id", "category", "price_dh"}.issubset(service_price_columns)
    promo_code_columns = {column["name"] for column in inspect(engine).get_columns("promo_codes")}
    assert {"code", "label", "active"}.issubset(promo_code_columns)
    promo_discount_columns = {column["name"] for column in inspect(engine).get_columns("promo_discounts")}
    assert {"promo_code", "service_id", "category", "price_dh"}.issubset(promo_discount_columns)
    closed_date_columns = {column["name"] for column in inspect(engine).get_columns("closed_dates")}
    assert {"date_iso", "label", "active"}.issubset(closed_date_columns)
    time_slot_columns = {column["name"] for column in inspect(engine).get_columns("time_slots")}
    assert {"slot_id", "label", "period", "active"}.issubset(time_slot_columns)
    center_columns = {column["name"] for column in inspect(engine).get_columns("centers")}
    assert {"center_id", "name", "details", "active"}.issubset(center_columns)
    admin_text_columns = {column["name"] for column in inspect(engine).get_columns("admin_texts")}
    assert {"text_key", "title", "body"}.issubset(admin_text_columns)
    notification_columns = {column["name"] for column in inspect(engine).get_columns("booking_notification_settings")}
    assert {"settings_key", "enabled", "phone_number", "template_name", "template_language"}.issubset(
        notification_columns
    )

    with session_scope(engine) as session:
        service_ids = {row.service_id for row in session.scalars(select(ServiceRow)).all()}
    assert {"svc_ext", "svc_cpl", "svc_pol", "svc_moto"}.issubset(service_ids)


def test_init_db_migrates_legacy_customer_vehicles_to_normalized_refs():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE customer_vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_phone VARCHAR(32),
                category VARCHAR(16),
                model VARCHAR(120),
                color VARCHAR(60),
                label VARCHAR(180),
                active BOOLEAN,
                last_used_at DATETIME,
                created_at DATETIME
            )
        """))
        connection.execute(text("""
            INSERT INTO customer_vehicles
                (customer_phone, category, model, color, label, active, created_at)
            VALUES
                ('212665883062', 'B', 'BMW 330i', 'Noir', 'BMW 330i — Noir', 1, CURRENT_TIMESTAMP)
        """))

    init_db(engine)

    vehicle_columns = {column["name"] for column in inspect(engine).get_columns("customer_vehicles")}
    assert {"model_id", "color_id"}.issubset(vehicle_columns)
    with session_scope(engine) as session:
        model = session.scalars(select(VehicleModel)).one()
        color = session.scalars(select(VehicleColor)).one()
        vehicle = session.scalars(select(CustomerVehicle)).one()
        assert model.category == "B"
        assert model.name == "BMW 330i"
        assert model.normalized_name == "bmw 330i"
        assert color.name == "Noir"
        assert color.normalized_name == "noir"
        assert vehicle.model_id == model.id
        assert vehicle.color_id == color.id


def test_customer_vehicle_booking_status_and_reminder_rows_round_trip():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    appointment = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)

    with session_scope(engine) as session:
        customer = Customer(phone="212665883062", display_name="Oussama")
        session.add(customer)
        session.flush()
        session.add(CustomerName(customer_phone=customer.phone, display_name="Oussama", normalized_name="oussama"))

        model = VehicleModel(category="B", name="BMW 330i", normalized_name="bmw 330i")
        color = VehicleColor(name="Noir", normalized_name="noir")
        session.add_all([model, color])
        session.flush()

        vehicle = CustomerVehicle(
            customer_phone=customer.phone,
            category="B",
            model_id=model.id,
            color_id=color.id,
            model="BMW 330i",
            color="Noir",
            label="BMW 330i — Noir",
        )
        session.add(vehicle)
        session.flush()

        booking = BookingRow(
            customer_phone=customer.phone,
            customer_vehicle_id=vehicle.id,
            status="confirmed",
            customer_name="Oussama",
            vehicle_type="B — Berline / SUV",
            car_model="BMW 330i",
            color="Noir",
            service_id="svc_cpl",
            service_bucket="wash",
            service_label="Le Complet",
            price_dh=110,
            price_regular_dh=125,
            promo_code="YS26",
            promo_label="Yasmine Signature",
            location_mode="home",
            geo="📍 33.5, -7.6",
            address="Bouskoura",
            date_label="01/05/2026",
            slot="slot_9_11",
            note="Portail bleu",
            appointment_start_at=appointment,
            timezone_name="Africa/Casablanca",
        )
        session.add(booking)
        session.flush()

        session.add(
            BookingStatusEventRow(
                booking_id=booking.id,
                from_status="awaiting_confirmation",
                to_status="confirmed",
                actor="customer",
                note="Confirmation WhatsApp",
            )
        )
        rule = ReminderRuleRow(
            name="H-1",
            offset_minutes_before=60,
            template_name="booking_reminder_h1",
        )
        session.add(rule)
        session.flush()
        session.add(
            BookingReminderRow(
                booking_id=booking.id,
                rule_id=rule.id,
                kind="H-1",
                scheduled_for=datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
            )
        )

    with session_scope(engine) as session:
        booking = session.scalars(select(BookingRow)).one()
        assert booking.customer.phone == "212665883062"
        assert booking.customer.display_name == "Oussama"
        assert booking.customer_name == "Oussama"
        assert booking.vehicle.label == "BMW 330i — Noir"
        assert booking.vehicle.vehicle_model.name == "BMW 330i"
        assert booking.vehicle.vehicle_color.name == "Noir"
        assert booking.car_model == "BMW 330i"
        assert booking.color == "Noir"
        assert booking.address == "Bouskoura"
        assert booking.note == "Portail bleu"
        assert booking.price_regular_dh == 125
        assert booking.promo_label == "Yasmine Signature"
        assert booking.status == "confirmed"
        assert booking.status_events[0].to_status == "confirmed"
        assert booking.reminders[0].rule.name == "H-1"


def _alembic_upgrade(db_url: str, revision: str = "head") -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), os.pardir, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), os.pardir, "migrations"))
    prior = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = db_url
    try:
        command.upgrade(cfg, revision)
    finally:
        if prior is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prior


def _alembic_downgrade(db_url: str, revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), os.pardir, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), os.pardir, "migrations"))
    prior = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = db_url
    try:
        command.downgrade(cfg, revision)
    finally:
        if prior is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prior


def test_migration_0006_sqlite_roundtrip(tmp_path):
    """Migration 0006 upgrades cleanly on SQLite, downgrades, and re-upgrades.

    Postgres-only constructs (partial unique index, CHECK constraint, FK redefinition)
    are skipped — the SQLite path only verifies columns, tables, and the indexes
    that work portably.
    """
    db_path = tmp_path / "ewash_0006.db"
    db_url = f"sqlite+pysqlite:///{db_path}"

    _alembic_upgrade(db_url, "head")

    engine = make_engine(db_url)
    insp = inspect(engine)

    bookings_columns = {c["name"] for c in insp.get_columns("bookings")}
    assert "client_request_id" in bookings_columns
    assert "source" in bookings_columns

    tables = set(insp.get_table_names())
    assert {"customer_tokens", "data_erasure_audit"}.issubset(tables)

    bookings_indexes = {idx["name"] for idx in insp.get_indexes("bookings")}
    assert "ix_bookings_source" in bookings_indexes
    assert "ix_bookings_customer_phone_created_at" in bookings_indexes

    token_indexes = {idx["name"] for idx in insp.get_indexes("customer_tokens")}
    assert {"ix_customer_tokens_phone", "ix_customer_tokens_last_used"}.issubset(token_indexes)

    erasure_indexes = {idx["name"] for idx in insp.get_indexes("data_erasure_audit")}
    assert "ix_data_erasure_audit_performed_at" in erasure_indexes

    token_uniques = {tuple(item["column_names"]) for item in insp.get_unique_constraints("customer_tokens")}
    assert ("token_hash",) in token_uniques

    # source DEFAULT applies to inserts that omit the column.
    with session_scope(engine) as sess:
        sess.add(Customer(phone="212600000000", display_name="Test"))
        sess.flush()
        sess.add(BookingRow(
            customer_phone="212600000000",
            status="draft",
            ref="EW-2026-9999",
            customer_name="Test",
        ))
    with engine.connect() as conn:
        result = conn.execute(text("SELECT source FROM bookings WHERE ref='EW-2026-9999'")).scalar_one()
        assert result == "whatsapp"

    _alembic_downgrade(db_url, "20260506_0005")

    engine2 = make_engine(db_url)
    insp2 = inspect(engine2)

    bookings_columns_after_down = {c["name"] for c in insp2.get_columns("bookings")}
    assert "client_request_id" not in bookings_columns_after_down
    assert "source" not in bookings_columns_after_down
    tables_after_down = set(insp2.get_table_names())
    assert "customer_tokens" not in tables_after_down
    assert "data_erasure_audit" not in tables_after_down

    _alembic_upgrade(db_url, "head")

    engine3 = make_engine(db_url)
    insp3 = inspect(engine3)
    bookings_columns_redo = {c["name"] for c in insp3.get_columns("bookings")}
    assert "client_request_id" in bookings_columns_redo
    assert "source" in bookings_columns_redo


def test_migration_0006_indexes_present():
    """Postgres-only: confirm all indexes from migration 0006 exist after upgrade.

    Skipped unless EWASH_TEST_POSTGRES_URL points at a fresh Postgres database.
    """
    pg_url = os.environ.get("EWASH_TEST_POSTGRES_URL")
    if not pg_url:
        pytest.skip("EWASH_TEST_POSTGRES_URL not set — Postgres-only check")

    _alembic_upgrade(pg_url, "head")
    engine = make_engine(pg_url)
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname='public' AND tablename IN ('bookings','customer_tokens','data_erasure_audit')"
        )).fetchall()
        names = {r[0] for r in result}
        for expected in (
            "ix_bookings_client_request_id_partial",
            "ix_bookings_source",
            "ix_bookings_customer_phone_created_at",
            "ix_customer_tokens_phone",
            "ix_customer_tokens_last_used",
            "ix_data_erasure_audit_performed_at",
        ):
            assert expected in names, f"missing index: {expected}"


def test_migration_0006_on_update_cascade():
    """Postgres-only: bookings → customers FK has ON UPDATE CASCADE after migration 0006."""
    pg_url = os.environ.get("EWASH_TEST_POSTGRES_URL")
    if not pg_url:
        pytest.skip("EWASH_TEST_POSTGRES_URL not set — Postgres-only check")

    _alembic_upgrade(pg_url, "head")
    engine = make_engine(pg_url)
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT confupdtype FROM pg_constraint "
            "WHERE conname = 'bookings_customer_phone_fkey'"
        )).fetchone()
        assert result is not None, "bookings_customer_phone_fkey constraint not found"
        assert result[0] == "c", f"expected 'c' (CASCADE), got {result[0]!r}"


def test_migration_0006_source_check_rejects_invalid():
    """Postgres-only: CHECK on bookings.source rejects values outside the allow-list."""
    pg_url = os.environ.get("EWASH_TEST_POSTGRES_URL")
    if not pg_url:
        pytest.skip("EWASH_TEST_POSTGRES_URL not set — Postgres-only check")

    _alembic_upgrade(pg_url, "head")
    engine = make_engine(pg_url)
    with engine.connect() as conn:
        with pytest.raises(Exception):
            conn.execute(text(
                "INSERT INTO customers (phone, display_name, booking_count) "
                "VALUES ('212600000001','Test',0)"
            ))
            conn.execute(text(
                "INSERT INTO bookings (customer_phone, status, ref, customer_name, source) "
                "VALUES ('212600000001','draft','EW-2026-CHECK','Test','bogus')"
            ))
            conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# PWA integration models (br-ewash-6pa.1.3 / 1.4 / 1.5)
# ─────────────────────────────────────────────────────────────────────────────


def test_create_all_emits_pwa_integration_tables_and_columns():
    """Fresh SQLite via `create_all` must produce every PWA-integration entity.

    Mirrors `test_migration_0006_sqlite_roundtrip` but exercises the model-
    declaration path directly so a missing __tablename__ / mapped_column is
    caught even on dialects where the migration's defensive create_all branch
    isn't hit.
    """
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    insp = inspect(engine)

    tables = set(insp.get_table_names())
    assert {"customer_tokens", "data_erasure_audit"}.issubset(tables)

    bookings_columns = {c["name"] for c in insp.get_columns("bookings")}
    assert {"client_request_id", "source"}.issubset(bookings_columns)

    token_columns = {c["name"] for c in insp.get_columns("customer_tokens")}
    assert {
        "id",
        "token_hash",
        "customer_phone",
        "created_at",
        "last_used_at",
    }.issubset(token_columns)

    erasure_columns = {c["name"] for c in insp.get_columns("data_erasure_audit")}
    assert {
        "id",
        "phone_hash",
        "actor",
        "deleted_count",
        "anonymized_bookings",
        "performed_at",
        "notes",
    }.issubset(erasure_columns)


def test_customer_token_roundtrip_via_orm():
    """Insert + read a CustomerTokenRow through SQLAlchemy ORM."""
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    with session_scope(engine) as session:
        session.add(Customer(phone="212600000010", display_name="Alice"))
        session.flush()
        session.add(CustomerTokenRow(
            customer_phone="212600000010",
            token_hash="a" * 64,
        ))

    with session_scope(engine) as session:
        token = session.scalars(select(CustomerTokenRow)).one()
        assert token.customer_phone == "212600000010"
        assert token.token_hash == "a" * 64
        assert token.last_used_at is None
        # Relationship roundtrip: Customer.tokens loads the row back.
        customer = session.get(Customer, "212600000010")
        assert len(customer.tokens) == 1
        assert customer.tokens[0].token_hash == "a" * 64


def test_customer_token_hash_unique_constraint():
    """A second token with the same hash must fail the unique constraint."""
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    with session_scope(engine) as session:
        session.add(Customer(phone="212600000020", display_name="Bob"))
        session.flush()
        session.add(CustomerTokenRow(customer_phone="212600000020", token_hash="b" * 64))

    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with session_scope(engine) as session:
            session.add(CustomerTokenRow(customer_phone="212600000020", token_hash="b" * 64))


def test_customer_token_cascade_delete_when_customer_deleted():
    """Customer.tokens cascade-delete-orphan removes child tokens with the parent."""
    engine = make_engine("sqlite+pysqlite:///:memory:")
    # Enable SQLite FK enforcement so ondelete=CASCADE behaves as on Postgres.
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()
    init_db(engine)
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()

    with session_scope(engine) as session:
        session.add(Customer(phone="212600000030", display_name="Carol"))
        session.flush()
        session.add(CustomerTokenRow(customer_phone="212600000030", token_hash="c" * 64))

    with session_scope(engine) as session:
        customer = session.get(Customer, "212600000030")
        session.delete(customer)

    with session_scope(engine) as session:
        # ORM-level cascade (relationship cascade="all, delete-orphan") removes children
        # when the parent is deleted via session.delete().
        assert session.scalars(select(CustomerTokenRow)).all() == []


def test_data_erasure_audit_roundtrip_via_orm():
    """Insert + read a DataErasureAuditRow through ORM. Privacy: no raw phone column."""
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    with session_scope(engine) as session:
        session.add(DataErasureAuditRow(
            phone_hash="d" * 64,
            actor="admin:operator1",
            deleted_count=2,
            anonymized_bookings=5,
            notes="Support ticket #12345",
        ))

    with session_scope(engine) as session:
        audit = session.scalars(select(DataErasureAuditRow)).one()
        assert audit.phone_hash == "d" * 64
        assert audit.actor == "admin:operator1"
        assert audit.deleted_count == 2
        assert audit.anonymized_bookings == 5
        assert audit.notes == "Support ticket #12345"
        assert audit.performed_at is not None
        # Server default supplies the timestamp without the caller setting it.
        assert audit.id is not None


def test_data_erasure_audit_has_no_pii_columns():
    """Privacy invariant: no field stores raw phone or other direct PII."""
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("data_erasure_audit")}
    # Only phone_hash is allowed; never `phone` or `customer_phone`.
    assert "phone" not in columns
    assert "customer_phone" not in columns
    # phone_hash IS expected.
    assert "phone_hash" in columns


def test_bookings_source_default_is_whatsapp():
    """A BookingRow constructed without `source` defaults to 'whatsapp'.

    Belt-and-suspenders: both the Python-side `default="whatsapp"` and the
    DB-side `server_default="whatsapp"` should produce the same result. The
    persistence layer always sets it explicitly post-integration, but legacy
    WhatsApp insert paths that omit the column must still land as 'whatsapp'.
    """
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    with session_scope(engine) as session:
        session.add(Customer(phone="212600000040", display_name="Dan"))
        session.flush()
        session.add(BookingRow(
            customer_phone="212600000040", status="draft",
            ref="EW-2026-SRC1", customer_name="Dan",
        ))

    with session_scope(engine) as session:
        booking = session.scalars(select(BookingRow)).one()
        assert booking.source == "whatsapp"


def test_bookings_source_accepts_api_and_admin_via_orm():
    """ORM `source='api'` and `source='admin'` roundtrip cleanly (Pydantic enforces
    the allow-list at the API boundary; the model just stores the string)."""
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    with session_scope(engine) as session:
        session.add(Customer(phone="212600000050", display_name="Eve"))
        session.flush()
        session.add(BookingRow(
            customer_phone="212600000050", status="draft", ref="EW-2026-SRC2",
            customer_name="Eve", source="api",
        ))
        session.add(BookingRow(
            customer_phone="212600000050", status="draft", ref="EW-2026-SRC3",
            customer_name="Eve", source="admin",
        ))

    with session_scope(engine) as session:
        sources = {
            row.source
            for row in session.scalars(select(BookingRow).order_by(BookingRow.ref)).all()
        }
        assert sources == {"api", "admin"}


def test_bookings_client_request_id_is_nullable_and_roundtrips():
    """Two bookings without client_request_id co-exist; one with a value roundtrips."""
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    with session_scope(engine) as session:
        session.add(Customer(phone="212600000060", display_name="Fay"))
        session.flush()
        session.add(BookingRow(
            customer_phone="212600000060", status="draft", ref="EW-2026-CRI1",
            customer_name="Fay",
        ))
        session.add(BookingRow(
            customer_phone="212600000060", status="draft", ref="EW-2026-CRI2",
            customer_name="Fay",
        ))
        session.add(BookingRow(
            customer_phone="212600000060", status="draft", ref="EW-2026-CRI3",
            customer_name="Fay", client_request_id="11111111-2222-3333-4444-555555555555",
        ))

    with session_scope(engine) as session:
        rows = list(
            session.scalars(select(BookingRow).order_by(BookingRow.ref)).all()
        )
        assert rows[0].client_request_id is None
        assert rows[1].client_request_id is None
        assert rows[2].client_request_id == "11111111-2222-3333-4444-555555555555"
