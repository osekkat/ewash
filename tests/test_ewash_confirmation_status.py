from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.admin_i18n import t
from app.config import settings
from app.db import init_db, make_engine, session_scope
from app.main import app
from app.models import BookingReminderRow, BookingRow, BookingStatusEventRow, ReminderRuleRow
from app.persistence import _configured_engine, admin_dashboard_summary, confirm_booking_by_ewash, persist_confirmed_booking
from tests.test_booking_persistence import _sample_booking


def test_customer_confirmation_creates_pending_ewash_confirmation_status():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    booking = _sample_booking()

    persist_confirmed_booking(booking, engine=engine)

    with session_scope(engine) as session:
        saved = session.scalars(select(BookingRow)).one()
        event = session.scalars(select(BookingStatusEventRow)).one()

    assert saved.status == "pending_ewash_confirmation"
    assert event.from_status == "awaiting_confirmation"
    assert event.to_status == "pending_ewash_confirmation"
    assert event.actor == "customer"


def test_pending_ewash_confirmation_is_localized_for_admin():
    assert t("status.pending_ewash_confirmation", "fr") == "À confirmer par eWash"
    assert t("status.pending_ewash_confirmation", "en") == "Pending eWash confirmation"
    assert t("status.confirmed", "fr") == "Confirmée par eWash"
    assert t("status.confirmed", "en") == "Confirmed by eWash"


def test_admin_dashboard_shows_pending_ewash_confirmation_metric_and_status(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'pending-ewash.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    persist_confirmed_booking(_sample_booking(), engine=engine)

    summary = admin_dashboard_summary(engine=engine)
    assert summary.pending_ewash_confirmation == 1

    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    _configured_engine.cache_clear()
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    dashboard = client.get("/admin")
    bookings = client.get("/admin/bookings")

    assert dashboard.status_code == 200
    assert "À confirmer par eWash" in dashboard.text
    assert "<div class=\"metric-value\">1</div>" in dashboard.text
    assert bookings.status_code == 200
    assert "À confirmer par eWash" in bookings.text
    _configured_engine.cache_clear()


def test_admin_bookings_page_shows_ewash_confirm_button_only_for_pending(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-ewash-confirm-button.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    pending = _sample_booking(phone="212600000101")
    confirmed = _sample_booking(phone="212600000102")
    confirmed.date_iso = "2099-05-01"
    persist_confirmed_booking(pending, engine=engine)
    persist_confirmed_booking(confirmed, engine=engine)
    confirm_booking_by_ewash(confirmed.ref, engine=engine)

    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    _configured_engine.cache_clear()
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.get("/admin/bookings")

    assert response.status_code == 200
    assert "Confirmer eWash" in response.text
    assert f'name="ref" value="{pending.ref}"' in response.text
    assert f'name="ref" value="{confirmed.ref}"' not in response.text
    assert "Confirmée par eWash" in response.text
    _configured_engine.cache_clear()


def test_admin_booking_confirm_route_changes_status_writes_event_and_h2_once(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-ewash-confirm-route.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    booking = _sample_booking(phone="212600000103")
    booking.date_iso = "2099-05-01"
    booking.date_label = "01/05/2099"
    booking.slot_id = "slot_9_11"
    booking.slot = "09h – 11h"
    persist_confirmed_booking(booking, engine=engine)
    with session_scope(engine) as session:
        session.add(
            ReminderRuleRow(
                name="H-2",
                enabled=True,
                offset_minutes_before=120,
                template_name="booking_reminder_h2",
            )
        )

    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    _configured_engine.cache_clear()
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.post("/admin/bookings/confirm?lang=fr", data={"ref": booking.ref}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/bookings?lang=fr&confirmed=1"
    with session_scope(engine) as session:
        saved = session.scalars(select(BookingRow).where(BookingRow.ref == booking.ref)).one()
        events = session.scalars(
            select(BookingStatusEventRow).where(BookingStatusEventRow.booking_id == saved.id).order_by(BookingStatusEventRow.id)
        ).all()
        reminders = session.scalars(select(BookingReminderRow).where(BookingReminderRow.booking_id == saved.id)).all()

        assert saved.status == "confirmed"
        assert events[-1].from_status == "pending_ewash_confirmation"
        assert events[-1].to_status == "confirmed"
        assert events[-1].actor == "admin"
        assert events[-1].note == "Confirmation eWash depuis le portail admin"
        assert len(reminders) == 1
        assert reminders[0].kind == "H-2"
        assert reminders[0].status == "pending"
        assert reminders[0].rule.template_name == "booking_reminder_h2"
        assert reminders[0].scheduled_for.hour == 7

    repeated = client.post("/admin/bookings/confirm?lang=fr", data={"ref": booking.ref})
    assert repeated.status_code == 200
    with session_scope(engine) as session:
        saved = session.scalars(select(BookingRow).where(BookingRow.ref == booking.ref)).one()
        reminders = session.scalars(select(BookingReminderRow).where(BookingReminderRow.booking_id == saved.id)).all()
        assert saved.status == "confirmed"
        assert len(reminders) == 1
    _configured_engine.cache_clear()


def test_confirm_booking_by_ewash_rejects_non_pending_without_changes():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    booking = _sample_booking(phone="212600000104")
    booking.date_iso = "2099-05-01"
    persist_confirmed_booking(booking, engine=engine)
    confirm_booking_by_ewash(booking.ref, engine=engine)

    with pytest.raises(ValueError):
        confirm_booking_by_ewash(booking.ref, engine=engine)

    with session_scope(engine) as session:
        saved = session.scalars(select(BookingRow).where(BookingRow.ref == booking.ref)).one()
        events = session.scalars(select(BookingStatusEventRow).where(BookingStatusEventRow.booking_id == saved.id)).all()
        reminders = session.scalars(select(BookingReminderRow).where(BookingReminderRow.booking_id == saved.id)).all()

    assert saved.status == "confirmed"
    assert [event.to_status for event in events].count("confirmed") == 1
    assert len(reminders) == 1
