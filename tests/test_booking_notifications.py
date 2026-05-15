import logging

import pytest

from app.booking import Booking
from app.config import settings
from app.db import init_db, make_engine
from app import meta
from app.notifications import (
    booking_notification_parameters,
    get_booking_notification_settings,
    notification_cache_clear,
    notify_booking_confirmation,
    notify_booking_confirmation_safe,
    upsert_booking_notification_settings,
)


def _sample_booking() -> Booking:
    return Booking(
        phone="212665883062",
        name="Oussama",
        vehicle_type="B — Berline / SUV",
        category="B",
        car_model="BMW 330i",
        color="Noir",
        service="svc_cpl",
        service_label="Le Complet — 125 DH",
        price_dh=125,
        location_mode="home",
        address="Bouskoura, portail bleu",
        date_label="Demain",
        slot="09h – 11h",
        note="Appeler en arrivant",
        ref="EW-2026-0001",
    )


def test_booking_notification_settings_normalize_admin_values():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    config = upsert_booking_notification_settings(
        enabled=True,
        phone_number="+212 665 883 062",
        template_name="new_booking_alert",
        template_language="fr",
        engine=engine,
    )

    assert config.enabled is True
    assert config.phone_number == "212665883062"
    assert config.template_name == "new_booking_alert"
    assert get_booking_notification_settings(engine=engine) == config


def test_booking_notification_parameters_include_addons_and_total():
    booking = _sample_booking()
    booking.addon_service = "svc_pol"
    booking.addon_service_label = "Le Polissage — 963 DH (-10%)"
    booking.addon_price_dh = 963

    params = booking_notification_parameters(booking, event_label="Reservation mise a jour")

    assert params == [
        "Reservation mise a jour",
        "EW-2026-0001",
        "Oussama",
        "+212665883062",
        "B — Berline / SUV - BMW 330i Noir",
        "Le Complet — 125 DH + Esthetique: Le Polissage — 963 DH (-10%)",
        "Demain - 09h – 11h",
        "Bouskoura, portail bleu",
        "1088 DH",
        "Appeler en arrivant",
    ]


@pytest.mark.asyncio
async def test_notify_booking_confirmation_sends_configured_template(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'booking-notifications.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    notification_cache_clear()
    upsert_booking_notification_settings(
        enabled=True,
        phone_number="+212 665 883 062",
        template_name="new_booking_alert",
        template_language="fr",
    )
    sent = []

    async def fake_send_template(to, template_name, *, language_code, body_parameters):
        sent.append((to, template_name, language_code, body_parameters))
        return {"messages": [{"id": "wamid.staff"}]}

    monkeypatch.setattr(meta, "send_template", fake_send_template)

    assert await notify_booking_confirmation(_sample_booking(), event_label="Nouvelle reservation") is True

    assert sent == [
        (
            "212665883062",
            "new_booking_alert",
            "fr",
            [
                "Nouvelle reservation",
                "EW-2026-0001",
                "Oussama",
                "+212665883062",
                "B — Berline / SUV - BMW 330i Noir",
                "Le Complet — 125 DH",
                "Demain - 09h – 11h",
                "Bouskoura, portail bleu",
                "125 DH",
                "Appeler en arrivant",
            ],
        )
    ]
    notification_cache_clear()


@pytest.mark.asyncio
async def test_notify_booking_confirmation_forces_staff_language_fr(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'booking-notifications-language.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    notification_cache_clear()
    upsert_booking_notification_settings(
        enabled=True,
        phone_number="+212 665 883 062",
        template_name="new_booking_alert",
        template_language="en",
    )
    sent = []

    async def fake_send_template(to, template_name, *, language_code, body_parameters):
        sent.append(language_code)
        return {"messages": [{"id": "wamid.staff"}]}

    monkeypatch.setattr(meta, "send_template", fake_send_template)

    assert await notify_booking_confirmation(_sample_booking(), event_label="Nouvelle reservation") is True

    assert sent == ["fr"]
    notification_cache_clear()


@pytest.mark.asyncio
async def test_notify_booking_confirmation_safe_logs_success(monkeypatch, caplog):
    async def fake_notify(booking, *, event_label):
        return True

    monkeypatch.setattr("app.notifications.notify_booking_confirmation", fake_notify)
    caplog.set_level(logging.INFO, logger="app.notifications")

    await notify_booking_confirmation_safe(_sample_booking(), event_label="Nouvelle réservation PWA")

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "notifications.staff_alert sent ref=EW-2026-0001" in messages
    assert "event=Nouvelle réservation PWA" in messages
    assert "result=True" in messages


@pytest.mark.asyncio
async def test_notify_booking_confirmation_safe_logs_false_result_as_error(monkeypatch, caplog):
    async def failed_notify(booking, *, event_label):
        return False

    monkeypatch.setattr("app.notifications.notify_booking_confirmation", failed_notify)
    caplog.set_level(logging.ERROR, logger="app.notifications")

    await notify_booking_confirmation_safe(_sample_booking(), event_label="Nouvelle réservation PWA")

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "notifications.staff_alert failed ref=EW-2026-0001" in messages
    assert "event=Nouvelle réservation PWA" in messages
    assert "result=False" in messages


@pytest.mark.asyncio
async def test_notify_booking_confirmation_safe_logs_and_swallows_failure(monkeypatch, caplog):
    async def failing_notify(booking, *, event_label):
        raise RuntimeError("meta unavailable")

    monkeypatch.setattr("app.notifications.notify_booking_confirmation", failing_notify)
    caplog.set_level(logging.ERROR, logger="app.notifications")

    await notify_booking_confirmation_safe(_sample_booking(), event_label="Nouvelle réservation PWA")

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "notifications.staff_alert failed ref=EW-2026-0001" in messages
    assert "event=Nouvelle réservation PWA" in messages
    assert "result=exception" in messages
