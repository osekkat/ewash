import asyncio

from sqlalchemy import select

from app import handlers, meta, state
from app.booking import Booking
from app.config import settings
from app.db import init_db, make_engine, session_scope
from app.models import (
    BookingLineItemRow,
    BookingRefCounterRow,
    BookingRow,
    BookingStatusEventRow,
    ConversationEventRow,
    ConversationSessionRow,
    Customer,
    CustomerName,
    CustomerVehicle,
    VehicleColor,
    VehicleModel,
    WhatsappMessageRow,
)
from app.persistence import (
    admin_customer_list,
    admin_dashboard_summary,
    assign_booking_ref,
    get_returning_customer_profile,
    persist_booking_identity,
    persist_confirmed_booking,
    persist_booking_addon,
    persist_customer_contact,
    persist_customer_name,
    persist_customer_bot_stage,
    persist_whatsapp_inbound_message,
    _configured_engine,
)


def _sample_booking(phone: str = "212665883062") -> Booking:
    booking = Booking(phone=phone)
    booking.name = "Oussama"
    booking.vehicle_type = "B — Berline / SUV"
    booking.category = "B"
    booking.car_model = "BMW 330i"
    booking.color = "Noir"
    booking.service = "svc_cpl"
    booking.service_bucket = "wash"
    booking.service_label = "Le Complet — 110 DH"
    booking.price_dh = 110
    booking.price_regular_dh = 125
    booking.promo_code = "YS26"
    booking.promo_label = "Yasmine Signature"
    booking.location_mode = "home"
    booking.geo = "📍 33.5, -7.6"
    booking.location_name = "Villa Oussama"
    booking.location_address = "Bouskoura"
    booking.latitude = 33.5
    booking.longitude = -7.6
    booking.address = "Bouskoura, portail bleu"
    booking.date_label = "Demain"
    booking.date_iso = "2026-05-01"
    booking.slot_id = "slot_9_11"
    booking.slot = "09h – 11h"
    booking.note = "Appeler en arrivant"
    booking.assign_ref()
    return booking


def test_persist_confirmed_booking_upserts_customer_vehicle_and_status_event():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    booking = _sample_booking()

    row = persist_confirmed_booking(booking, engine=engine)

    assert row is not None
    assert row.ref == booking.ref
    assert row.status == "pending_ewash_confirmation"

    with session_scope(engine) as session:
        customer = session.get(Customer, "212665883062")
        assert customer is not None
        assert customer.display_name == "Oussama"
        assert customer.booking_count == 1

        vehicle = session.scalars(select(CustomerVehicle)).one()
        assert vehicle.customer_phone == "212665883062"
        assert vehicle.category == "B"
        assert vehicle.model == "BMW 330i"
        assert vehicle.color == "Noir"
        assert vehicle.label == "BMW 330i — Noir"
        assert vehicle.vehicle_model.name == "BMW 330i"
        assert vehicle.vehicle_model.normalized_name == "bmw 330i"
        assert vehicle.vehicle_color.name == "Noir"
        assert vehicle.vehicle_color.normalized_name == "noir"

        saved = session.scalars(select(BookingRow)).one()
        assert saved.customer_phone == "212665883062"
        assert saved.customer_vehicle_id == vehicle.id
        assert saved.customer_name == "Oussama"
        assert saved.service_id == "svc_cpl"
        assert saved.price_dh == 110
        assert saved.price_regular_dh == 125
        assert saved.promo_code == "YS26"
        assert saved.location_mode == "home"
        assert saved.geo == "📍 33.5, -7.6"
        assert saved.location_name == "Villa Oussama"
        assert saved.location_address == "Bouskoura"
        assert saved.latitude == 33.5
        assert saved.longitude == -7.6
        assert saved.address == "Bouskoura, portail bleu"
        assert saved.address_text == "Bouskoura, portail bleu"
        assert saved.appointment_date.isoformat() == "2026-05-01"
        assert saved.slot_id == "slot_9_11"
        assert saved.appointment_start_at.hour == 9
        assert saved.appointment_end_at.hour == 11
        assert saved.note == "Appeler en arrivant"
        assert saved.total_price_dh == 110
        assert "BMW 330i" in saved.raw_booking_json

        line_item = session.scalars(select(BookingLineItemRow)).one()
        assert line_item.booking_id == saved.id
        assert line_item.kind == "main"
        assert line_item.service_id == "svc_cpl"
        assert line_item.label_snapshot == "Le Complet — 110 DH"
        assert line_item.unit_price_dh == 110
        assert line_item.regular_price_dh == 125
        assert line_item.total_price_dh == 110

        event = session.scalars(select(BookingStatusEventRow)).one()
        assert event.booking_id == saved.id
        assert event.from_status == "awaiting_confirmation"
        assert event.to_status == "pending_ewash_confirmation"
        assert event.actor == "customer"


def test_persist_confirmed_booking_reuses_existing_vehicle_for_repeat_customer():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    first = _sample_booking()
    persist_confirmed_booking(first, engine=engine)

    second = _sample_booking()
    persist_confirmed_booking(second, engine=engine)

    with session_scope(engine) as session:
        assert len(session.scalars(select(CustomerVehicle)).all()) == 1
        assert len(session.scalars(select(BookingRow)).all()) == 2
        customer = session.get(Customer, "212665883062")
        assert customer.booking_count == 2


def test_persist_confirmed_booking_allows_one_customer_to_have_many_cars():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    first = _sample_booking()
    first.ref = "EW-2026-0201"
    persist_confirmed_booking(first, engine=engine)

    second = _sample_booking()
    second.ref = "EW-2026-0202"
    second.car_model = "Audi Q5"
    second.color = "Blanc"
    persist_confirmed_booking(second, engine=engine)

    with session_scope(engine) as session:
        customer = session.get(Customer, "212665883062")
        assert customer is not None
        assert customer.booking_count == 2
        assert len(customer.vehicles) == 2

        vehicles = session.scalars(select(CustomerVehicle).order_by(CustomerVehicle.id)).all()
        assert [vehicle.customer_phone for vehicle in vehicles] == ["212665883062", "212665883062"]
        assert [vehicle.label for vehicle in vehicles] == ["BMW 330i — Noir", "Audi Q5 — Blanc"]

        bookings = session.scalars(select(BookingRow).order_by(BookingRow.ref)).all()
        assert [booking.customer_vehicle_id for booking in bookings] == [vehicles[0].id, vehicles[1].id]
        assert bookings[0].customer.phone == "212665883062"
        assert bookings[1].customer.phone == "212665883062"


def test_persist_confirmed_booking_normalizes_vehicle_model_and_color_references():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    first = _sample_booking()
    persist_confirmed_booking(first, engine=engine)

    second = _sample_booking()
    second.ref = "EW-2026-9999"
    second.car_model = "  bmw   330I "
    second.color = " NOIR "
    persist_confirmed_booking(second, engine=engine)

    with session_scope(engine) as session:
        assert len(session.scalars(select(VehicleModel)).all()) == 1
        assert len(session.scalars(select(VehicleColor)).all()) == 1
        model = session.scalars(select(VehicleModel)).one()
        color = session.scalars(select(VehicleColor)).one()
        assert model.category == "B"
        assert model.name == "BMW 330i"
        assert model.normalized_name == "bmw 330i"
        assert color.name == "Noir"
        assert color.normalized_name == "noir"
        vehicle = session.scalars(select(CustomerVehicle)).one()
        assert vehicle.model_id == model.id
        assert vehicle.color_id == color.id
        assert len(session.scalars(select(BookingRow)).all()) == 2


def test_assign_booking_ref_advances_past_existing_db_refs_when_memory_counter_reset(monkeypatch):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    existing = _sample_booking(phone="212600000001")
    year = existing.ref.split("-")[1]
    existing.ref = f"EW-{year}-0007"
    persist_confirmed_booking(existing, engine=engine)

    # Simulates a Railway redeploy: the process-local counter resets to 0,
    # while Postgres still has prior confirmed booking refs.
    import app.booking as booking_store
    monkeypatch.setattr(booking_store, "_counter", 0)
    booking_store._bookings.clear()

    new_booking = _sample_booking(phone="212600000002")
    new_booking.ref = ""
    new_booking.created_at = ""

    ref = assign_booking_ref(new_booking, engine=engine)
    persist_confirmed_booking(new_booking, engine=engine)

    assert ref == f"EW-{year}-0008"
    assert new_booking.ref == f"EW-{year}-0008"
    with session_scope(engine) as session:
        refs = {row.ref for row in session.scalars(select(BookingRow)).all()}
        assert refs == {f"EW-{year}-0007", f"EW-{year}-0008"}
        assert session.get(Customer, "212600000002") is not None
        counter = session.get(BookingRefCounterRow, int(year))
        assert counter is not None
        assert counter.last_counter == 8


def test_persist_booking_addon_updates_confirmed_booking_row():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    booking = _sample_booking()
    persist_confirmed_booking(booking, engine=engine)

    persist_booking_addon(
        booking.ref,
        addon_service="svc_pol",
        addon_service_label="Le Polissage — 770 DH (-10%)",
        addon_price_dh=770,
        engine=engine,
    )

    with session_scope(engine) as session:
        saved = session.scalars(select(BookingRow)).one()
        assert saved.addon_service == "svc_pol"
        assert saved.addon_service_label == "Le Polissage — 770 DH (-10%)"
        assert saved.addon_price_dh == 770
        assert saved.total_price_dh == 880
        line_items = session.scalars(select(BookingLineItemRow).order_by(BookingLineItemRow.sort_order)).all()
        assert [(item.kind, item.service_id, item.total_price_dh) for item in line_items] == [
            ("main", "svc_cpl", 110),
            ("addon", "svc_pol", 770),
        ]


def test_admin_dashboard_summary_counts_db_rows_and_recent_bookings():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    booking = _sample_booking()
    persist_confirmed_booking(booking, engine=engine)

    summary = admin_dashboard_summary(engine=engine)

    assert summary.total_bookings == 1
    assert summary.confirmed_bookings == 0
    assert summary.pending_ewash_confirmation == 1
    assert summary.customers == 1
    assert summary.pending_reminders == 0
    assert len(summary.recent_bookings) == 1
    assert summary.recent_bookings[0].customer_name == "Oussama"
    assert summary.recent_bookings[0].service_label == "Le Complet — 110 DH"


def test_persist_customer_bot_stage_tracks_abandoned_price_list_stage():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    persist_customer_bot_stage("212600000003", "BOOK_SERVICE", engine=engine)

    with session_scope(engine) as session:
        customer = session.get(Customer, "212600000003")
        assert customer is not None
        assert customer.last_bot_stage == "BOOK_SERVICE"
        assert customer.last_bot_stage_label == "Liste des prix affichée"
        assert customer.last_bot_stage_at is not None
        assert customer.booking_count == 0
        conversation = session.scalars(select(ConversationSessionRow)).one()
        assert conversation.customer_phone == "212600000003"
        assert conversation.current_stage == "BOOK_SERVICE"
        event = session.scalars(select(ConversationEventRow)).one()
        assert event.session_id == conversation.id
        assert event.stage == "BOOK_SERVICE"
        assert event.stage_label == "Liste des prix affichée"

    customers = admin_customer_list(engine=engine)
    customer_item = next(item for item in customers if item.phone == "212600000003")
    assert customer_item.last_bot_stage == "BOOK_SERVICE"
    assert customer_item.last_bot_stage_label == "Liste des prix affichée"


def test_persist_customer_contact_captures_whatsapp_profile_before_booking():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    customer = persist_customer_contact(
        "212600000004",
        {"wa_id": "212600000004", "profile": {"name": "Hassan WhatsApp"}},
        engine=engine,
    )

    assert customer is not None
    assert customer.phone == "212600000004"
    assert customer.display_name == "Hassan WhatsApp"
    assert customer.whatsapp_profile_name == "Hassan WhatsApp"
    assert customer.whatsapp_wa_id == "212600000004"
    assert customer.booking_count == 0


def test_customer_name_history_keeps_multiple_names_and_latest_profile():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    persist_customer_name("212600000005", "Hassan", engine=engine)
    persist_customer_name("212600000005", "Samira", engine=engine)
    booking = _sample_booking(phone="212600000005")
    booking.name = "Samira"
    booking.car_model = "Nissan Sentra"
    booking.color = "Jaune"
    persist_booking_identity(booking, engine=engine)

    with session_scope(engine) as session:
        customer = session.get(Customer, "212600000005")
        assert customer is not None
        assert customer.display_name == "Samira"
        names = session.scalars(select(CustomerName).where(CustomerName.customer_phone == "212600000005")).all()
        assert sorted(name.display_name for name in names) == ["Hassan", "Samira"]
        vehicles = session.scalars(select(CustomerVehicle).where(CustomerVehicle.customer_phone == "212600000005")).all()
        assert len(vehicles) == 1
        assert vehicles[0].label == "Nissan Sentra — Jaune"
        assert vehicles[0].last_used_at is not None

    profile = get_returning_customer_profile("212600000005", engine=engine)
    assert profile is not None
    assert profile.display_name == "Samira"
    assert profile.vehicle_label == "Nissan Sentra — Jaune"
    assert profile.category == "B"
    assert profile.model == "Nissan Sentra"
    assert profile.color == "Jaune"


def test_handle_message_tracks_latest_stage_after_showing_price_list(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'bot-stages.db'}"
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    phone = "212600000004"
    sess = state.start_booking(phone)
    sess.state = "BOOK_PROMO_ASK"
    sess.booking.name = "Lead Prix"
    sess.booking.category = "B"
    sess.booking.location_mode = "center"
    sess.booking.center = "Stand Ewash — Bouskoura"
    sent_lists: list[tuple] = []

    async def fake_send_list(*args, **kwargs):
        sent_lists.append((args, kwargs))
        return {}

    monkeypatch.setattr(meta, "send_list", fake_send_list)

    asyncio.run(
        handlers.handle_message(
            {
                "from": phone,
                "type": "interactive",
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": "promo_no", "title": "Non, continuer"},
                },
            }
        )
    )

    assert sent_lists
    with session_scope(_configured_engine()) as session:
        customer = session.get(Customer, phone)
        assert customer is not None
        assert customer.display_name == "Lead Prix"
        assert customer.last_bot_stage == "BOOK_SERVICE"
        assert customer.last_bot_stage_label == "Liste des prix affichée"
        assert customer.booking_count == 0
    state.reset(phone)
    _configured_engine.cache_clear()


def test_persist_whatsapp_inbound_message_is_idempotent():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    message = {"id": "wamid.test-1", "from": "212665883062", "type": "text", "text": {"body": "hello"}}

    assert persist_whatsapp_inbound_message(message, {"profile": {"name": "Oussama"}}, engine=engine) is True
    assert persist_whatsapp_inbound_message(message, {"profile": {"name": "Oussama"}}, engine=engine) is False

    with session_scope(engine) as session:
        rows = session.scalars(select(WhatsappMessageRow)).all()
        assert len(rows) == 1
        assert rows[0].message_id == "wamid.test-1"
        assert rows[0].phone == "212665883062"
        assert rows[0].direction == "inbound"
        assert rows[0].processed_at is not None
        customer = session.get(Customer, "212665883062")
        assert customer is not None
        assert customer.display_name == "Oussama"
        assert customer.whatsapp_profile_name == "Oussama"


def test_handle_message_captures_customer_contact_on_first_hello(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'first-contact.db'}"
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    phone = "212600000005"
    sent_buttons: list[tuple] = []

    async def fake_send_buttons(*args, **kwargs):
        sent_buttons.append((args, kwargs))
        return {}

    monkeypatch.setattr(meta, "send_buttons", fake_send_buttons)

    asyncio.run(
        handlers.handle_message(
            {"id": "wamid.first-contact", "from": phone, "type": "text", "text": {"body": "hello"}},
            {"wa_id": phone, "profile": {"name": "Nadia WhatsApp"}},
        )
    )

    assert sent_buttons
    with session_scope(_configured_engine()) as session:
        customer = session.get(Customer, phone)
        assert customer is not None
        assert customer.display_name == "Nadia WhatsApp"
        assert customer.whatsapp_profile_name == "Nadia WhatsApp"
        assert customer.whatsapp_wa_id == phone
        assert customer.last_bot_stage == "MENU"
        assert customer.booking_count == 0
    state.reset(phone)
    _configured_engine.cache_clear()
