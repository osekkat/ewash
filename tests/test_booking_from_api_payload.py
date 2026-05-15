"""Tests for app.booking.from_api_payload."""
from __future__ import annotations

import logging
from dataclasses import fields

import pytest

from app.api_schemas import BookingCreateRequest
from app.booking import Booking, from_api_payload


_DEFAULT_VEHICLE = object()


def _make_payload(
    *,
    phone: str = "212611204502",
    name: str = "Test Client",
    category: str = "A",
    service_id: str = "svc_cpl",
    vehicle: object = _DEFAULT_VEHICLE,
    location_kind: str = "home",
    pin_address: str | None = "My House",
    address_details: str | None = "Gate 3",
    center_id: str | None = None,
    promo_code: str | None = None,
    note: str | None = "Please call",
    addon_ids: list[str] | None = None,
    client_request_id: str | None = None,
) -> BookingCreateRequest:
    payload: dict = {
        "phone": phone,
        "name": name,
        "category": category,
        "service_id": service_id,
        "date": "2026-06-15",
        "slot": "slot_9_11",
        "location": {"kind": location_kind},
    }
    if vehicle is _DEFAULT_VEHICLE:
        payload["vehicle"] = {"make": "Dacia Logan", "color": "Blanc"}
    elif vehicle is not None:
        payload["vehicle"] = vehicle
    if pin_address is not None:
        payload["location"]["pin_address"] = pin_address
    if address_details is not None:
        payload["location"]["address_details"] = address_details
    if center_id is not None:
        payload["location"]["center_id"] = center_id
    if promo_code is not None:
        payload["promo_code"] = promo_code
    if note is not None:
        payload["note"] = note
    if addon_ids is not None:
        payload["addon_ids"] = addon_ids
    if client_request_id is not None:
        payload["client_request_id"] = client_request_id
    return BookingCreateRequest(**payload)


def _booking_from(payload: BookingCreateRequest, **overrides) -> Booking:
    kwargs = {
        "server_price_dh": 125,
        "server_regular_price_dh": 140,
        "service_label": "Le Complet - 125 DH",
        "vehicle_label": "A - Citadine",
        "location_label": "A domicile",
        "date_label": "15/06/2026",
        "slot_label": "09h-11h",
    }
    kwargs.update(overrides)
    return from_api_payload(payload, **kwargs)


def test_basic_car_booking(caplog):
    caplog.set_level(logging.DEBUG, logger="app.booking")
    payload = _make_payload(category="A", service_id="svc_cpl", addon_ids=["svc_cuir", "svc_plastq"])

    booking = _booking_from(payload, server_price_dh=125)

    assert booking.phone == "212611204502"
    assert booking.category == "A"
    assert booking.service == "svc_cpl"
    assert booking.service_bucket == "wash"
    assert booking.price_dh == 125
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "ewash.booking.from_api" in messages
    assert "phone_hash=" in messages
    assert "category=A" in messages
    assert "service=svc_cpl" in messages
    assert "addons=2" in messages
    assert "212611204502" not in messages


def test_moto_branch_no_vehicle():
    payload = _make_payload(category="MOTO", vehicle=None, service_id="svc_moto")

    booking = _booking_from(payload, vehicle_label="Moto / Scooter")

    assert booking.car_model is None
    assert booking.color is None
    assert booking.service_bucket == "moto"


def test_promo_branch():
    payload = _make_payload(promo_code="YS26")

    booking = _booking_from(payload, promo_label="Partner Promo")

    assert booking.promo_code == "YS26"
    assert booking.promo_label == "Partner Promo"


def test_home_vs_center_location():
    payload_home = _make_payload(location_kind="home", pin_address="My House")
    booking_home = _booking_from(payload_home, location_label="A domicile")

    assert booking_home.location_mode == "home"
    assert booking_home.location_address == "My House"
    assert booking_home.center is None

    payload_center = _make_payload(
        location_kind="center",
        pin_address=None,
        address_details=None,
        center_id="c1",
    )
    booking_center = _booking_from(payload_center, location_label="Stand Bouskoura")

    assert booking_center.location_mode == "center"
    assert booking_center.center == "Stand Bouskoura"
    assert booking_center.center_id == "c1"


def test_client_request_id_threaded():
    payload = _make_payload(client_request_id="my-uuid-1234")

    booking = _booking_from(payload)

    assert booking.client_request_id == "my-uuid-1234"


def test_cleantext_applied_to_freetext_fields():
    payload = _make_payload(name="  Foo\u0000Bar  ", note="line1\nline2")

    booking = _booking_from(payload)

    assert booking.name == "FooBar"
    assert booking.note == "line1\nline2"


def test_unknown_service_raises_value_error():
    payload = _make_payload(service_id="svc_unknown")

    with pytest.raises(ValueError):
        _booking_from(payload)


def test_scratch_fields_default():
    payload = _make_payload()

    booking = _booking_from(payload)

    assert booking.when_page == 0
    assert booking.when_dates == []
    assert booking.ref is None
    assert booking.created_at is None
    assert booking.addon_service is None
    assert {field.name for field in fields(Booking)} == set(booking.__dict__)
