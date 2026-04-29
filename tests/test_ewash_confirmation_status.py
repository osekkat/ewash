from fastapi.testclient import TestClient
from sqlalchemy import select

from app.admin_i18n import t
from app.config import settings
from app.db import init_db, make_engine, session_scope
from app.main import app
from app.models import BookingRow, BookingStatusEventRow
from app.persistence import _configured_engine, admin_dashboard_summary, persist_confirmed_booking
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
