from datetime import datetime, timezone

from sqlalchemy import inspect, select, text

from app.db import init_db, make_engine, normalize_database_url, session_scope
from app.models import (
    BookingReminderRow,
    BookingRow,
    BookingStatusEventRow,
    Customer,
    CustomerVehicle,
    ReminderRuleRow,
    VehicleColor,
    VehicleModel,
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
        "customer_vehicles",
        "vehicle_models",
        "vehicle_colors",
        "bookings",
        "booking_status_events",
        "reminder_rules",
        "booking_reminders",
    }.issubset(tables)
    vehicle_columns = {column["name"] for column in inspect(engine).get_columns("customer_vehicles")}
    assert {"model_id", "color_id"}.issubset(vehicle_columns)


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
