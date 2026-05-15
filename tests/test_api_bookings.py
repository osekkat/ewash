"""Tests for POST /api/v1/bookings."""
from __future__ import annotations

import logging
from unittest import TestCase

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import api, catalog, notifications, persistence
from app.config import settings
from app.db import init_db, make_engine, session_scope
from app.models import BookingLineItemRow, BookingRow, BookingStatusEventRow, Customer, CustomerName
from app.rate_limit import limiter

case = TestCase()


def _client(*, raise_server_exceptions: bool = True) -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api.router)
    api.install_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


@pytest.fixture
def api_db(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'api-bookings.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    persistence._configured_engine.cache_clear()
    catalog.catalog_cache_clear()
    notifications.notification_cache_clear()
    try:
        yield engine
    finally:
        persistence._configured_engine.cache_clear()
        catalog.catalog_cache_clear()
        notifications.notification_cache_clear()


def _payload(**overrides) -> dict:
    payload = {
        "phone": "+212 611-204-502",
        "name": "  Oussama\u0000   Test  ",
        "category": "A",
        "vehicle": {"make": "Dacia   Logan", "color": " Blanc\u0000 "},
        "location": {
            "kind": "home",
            "pin_address": "Villa\u0000 Oussama",
            "address_details": "  Gate   3  ",
        },
        "promo_code": "ys26",
        "service_id": "svc_cpl",
        "date": "2026-06-15",
        "slot": "slot_9_11",
        "note": "  Sonner   deux fois\u0000  ",
        "addon_ids": [],
        "client_request_id": "booking-1234",
    }
    payload.update(overrides)
    return payload


def test_create_booking_happy_path_persists_pending_api_booking(api_db, caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")

    with _client() as client:
        response = client.post("/api/v1/bookings", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending_ewash_confirmation"
    assert body["ref"].startswith("EW-")
    assert body["price_dh"] == catalog.service_price("svc_cpl", "A", promo_code="YS26")
    assert body["total_dh"] == body["price_dh"]
    assert body["bookings_token"] == ""
    case.assertEqual(
        body["line_items"],
        [
            {
                "kind": "main",
                "service_id": "svc_cpl",
                "label": body["service_label"],
                "price_dh": body["price_dh"],
                "regular_price_dh": catalog.public_service_price("svc_cpl", "A"),
                "sort_order": 0,
            }
        ],
    )

    with session_scope(api_db) as session:
        row = session.scalars(select(BookingRow)).one()
        assert row.ref == body["ref"]
        assert row.status == "pending_ewash_confirmation"
        assert row.source == "api"
        assert row.customer_phone == "212611204502"
        assert row.customer_name == "Oussama Test"
        assert row.car_model == "Dacia Logan"
        assert row.color == "Blanc"
        assert row.address == "Gate 3"
        assert row.address_text == "Gate 3"
        assert row.location_address == "Villa Oussama"
        assert row.note == "Sonner deux fois"
        assert row.client_request_id == "booking-1234"
        assert row.appointment_date.isoformat() == "2026-06-15"
        assert row.slot_id == "slot_9_11"
        assert row.appointment_start_at.hour == 9
        assert row.appointment_end_at.hour == 11

        customer = session.get(Customer, "212611204502")
        assert customer is not None
        assert customer.display_name == "Oussama Test"
        name = session.scalars(select(CustomerName)).one()
        assert name.display_name == "Oussama Test"

        line_item = session.scalars(select(BookingLineItemRow)).one()
        assert line_item.booking_id == row.id
        assert line_item.kind == "main"
        assert line_item.service_id == "svc_cpl"
        assert line_item.unit_price_dh == body["price_dh"]

        event = session.scalars(select(BookingStatusEventRow)).one()
        assert event.booking_id == row.id
        assert event.to_status == "pending_ewash_confirmation"
        assert event.note == "Confirmation PWA"

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "ewash.api.bookings.create ref=" in messages
    assert "source=api" in messages
    assert "phone_hash=" in messages
    assert "212611204502" not in messages


def test_create_booking_single_addon_persists_legacy_and_line_item(api_db):
    addon_id = "svc_cuir"
    addon_regular = catalog.service_price(addon_id, "A", promo_code="YS26")
    expected_addon_price = round(addon_regular * 0.9)

    with _client() as client:
        response = client.post("/api/v1/bookings", json=_payload(addon_ids=[addon_id]))

    assert response.status_code == 200
    body = response.json()
    assert body["total_dh"] == body["price_dh"] + expected_addon_price
    case.assertEqual(
        body["line_items"][1],
        {
            "kind": "addon",
            "service_id": addon_id,
            "label": f"{catalog.service_name(addon_id)} — {expected_addon_price} DH (-10%)",
            "price_dh": expected_addon_price,
            "regular_price_dh": addon_regular,
            "sort_order": 10,
        },
    )

    with session_scope(api_db) as session:
        row = session.scalars(select(BookingRow)).one()
        assert row.addon_service == addon_id
        assert row.addon_service_label == body["line_items"][1]["label"]
        assert row.addon_price_dh == expected_addon_price
        assert row.total_price_dh == body["total_dh"]

        line_items = session.scalars(
            select(BookingLineItemRow).order_by(BookingLineItemRow.sort_order)
        ).all()
        assert [(item.kind, item.service_id, item.total_price_dh) for item in line_items] == [
            ("main", "svc_cpl", body["price_dh"]),
            ("addon", addon_id, expected_addon_price),
        ]
        assert line_items[1].regular_price_dh == addon_regular
        assert line_items[1].discount_label == "-10% Esthétique"


def test_create_booking_multiple_addons_appends_all_and_denormalizes_first(
    api_db,
    caplog,
):
    addon_ids = ["svc_cuir", "svc_plastq", "svc_cer6m"]
    addon_prices = [
        round(catalog.service_price(addon_id, "A", promo_code="YS26") * 0.9)
        for addon_id in addon_ids
    ]
    caplog.set_level(logging.INFO, logger="ewash.api")

    with _client() as client:
        response = client.post("/api/v1/bookings", json=_payload(addon_ids=addon_ids))

    assert response.status_code == 200
    body = response.json()
    assert body["total_dh"] == body["price_dh"] + sum(addon_prices)
    assert [item["service_id"] for item in body["line_items"]] == ["svc_cpl"] + addon_ids
    assert [item["price_dh"] for item in body["line_items"][1:]] == addon_prices
    assert [item["sort_order"] for item in body["line_items"]] == [0, 10, 20, 30]

    with session_scope(api_db) as session:
        row = session.scalars(select(BookingRow)).one()
        assert row.addon_service == addon_ids[0]
        assert row.addon_price_dh == addon_prices[0]
        assert row.total_price_dh == body["total_dh"]

        line_items = session.scalars(
            select(BookingLineItemRow).order_by(BookingLineItemRow.sort_order)
        ).all()
        assert [(item.kind, item.service_id, item.total_price_dh) for item in line_items] == [
            ("main", "svc_cpl", body["price_dh"]),
            ("addon", addon_ids[0], addon_prices[0]),
            ("addon", addon_ids[1], addon_prices[1]),
            ("addon", addon_ids[2], addon_prices[2]),
        ]

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "bookings.addons added ref=" in messages
    assert "count=3" in messages
    assert "addon_ids=svc_cuir,svc_plastq,svc_cer6m" in messages
    assert f"total_dh={body['total_dh']}" in messages


def test_create_booking_domain_rejection_returns_stable_error(api_db):
    with _client() as client:
        response = client.post(
            "/api/v1/bookings",
            json=_payload(service_id="svc_moto"),
        )

    assert response.status_code == 400
    assert response.headers["X-Ewash-Error-Code"] == "service_category_mismatch"
    body = response.json()
    assert body["error_code"] == "service_category_mismatch"
    assert body["field"] == "service_id"

    with session_scope(api_db) as session:
        assert session.scalars(select(BookingRow)).all() == []


def test_create_booking_rolls_back_if_late_write_fails(api_db, monkeypatch):
    def fail_name_write(phone, display_name, *, engine=None, session=None):
        raise RuntimeError("name history failed")

    monkeypatch.setattr(persistence, "persist_customer_name", fail_name_write)

    with _client(raise_server_exceptions=False) as client:
        response = client.post("/api/v1/bookings", json=_payload())

    assert response.status_code == 500
    assert response.json()["error_code"] == "internal_error"
    with session_scope(api_db) as session:
        assert session.scalars(select(BookingRow)).all() == []
        assert session.scalars(select(BookingLineItemRow)).all() == []
        assert session.scalars(select(BookingStatusEventRow)).all() == []
        assert session.scalars(select(CustomerName)).all() == []


def test_create_booking_returns_503_when_database_absent(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "")
    persistence._configured_engine.cache_clear()
    catalog.catalog_cache_clear()

    with _client() as client:
        response = client.post("/api/v1/bookings", json=_payload())

    assert response.status_code == 503
    assert response.headers["X-Ewash-Error-Code"] == "db_unavailable"
    assert response.json()["error_code"] == "db_unavailable"


def test_create_booking_schedules_staff_alert_after_commit(api_db, monkeypatch):
    calls = []

    async def fake_staff_alert(booking, *, event_label):
        with session_scope(api_db) as session:
            row = session.scalars(select(BookingRow).where(BookingRow.ref == booking.ref)).one()
            calls.append((booking.ref, event_label, row.status, row.source))

    monkeypatch.setattr(notifications, "notify_booking_confirmation_safe", fake_staff_alert)

    with _client() as client:
        response = client.post("/api/v1/bookings", json=_payload())

    assert response.status_code == 200
    assert calls == [
        (
            response.json()["ref"],
            "Nouvelle réservation PWA",
            "pending_ewash_confirmation",
            "api",
        )
    ]


def test_create_booking_staff_alert_failure_does_not_fail_response(api_db, monkeypatch, caplog):
    async def failing_staff_alert(booking, *, event_label):
        raise RuntimeError("meta down")

    monkeypatch.setattr(notifications, "notify_booking_confirmation", failing_staff_alert)
    caplog.set_level(logging.ERROR, logger="app.notifications")

    with _client() as client:
        response = client.post("/api/v1/bookings", json=_payload())

    assert response.status_code == 200
    with session_scope(api_db) as session:
        row = session.scalars(select(BookingRow)).one()
        assert row.ref == response.json()["ref"]
        assert row.status == "pending_ewash_confirmation"

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "notifications.staff_alert failed ref=" in messages
    assert "event=Nouvelle réservation PWA" in messages
