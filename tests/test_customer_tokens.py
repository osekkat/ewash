"""Tests for the PWA opaque-session-token persistence helpers.

`mint_customer_token` returns plaintext exactly once and stores only the
SHA-256 hash. `verify_customer_token` hashes the input and looks up;
optionally pins the lookup to an expected phone so a stolen token can't
be replayed against a different account.

The tests use SQLite in-memory and pin the engine via `engine=` kwarg
so the helpers don't try to resolve a global engine that conftest doesn't
configure.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import init_db, make_engine, session_scope
from app.models import BOOKING_STATUSES, BookingRow, Customer, CustomerTokenRow
from app.persistence import (
    _to_customer_view,
    list_bookings_for_token,
    mint_customer_token,
    verify_customer_token,
)
from app.security import hash_token


def _engine_with_customer(phone: str = "212600000100"):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    with session_scope(engine) as session:
        session.add(Customer(phone=phone, display_name="Test"))
    return engine, phone


def _add_booking(
    session,
    *,
    phone: str,
    ref: str,
    created_at: datetime,
    location_mode: str = "center",
    appointment_date: date | None = date(2026, 5, 20),
    slot_id: str = "slot_10_12",
) -> None:
    session.add(
        BookingRow(
            ref=ref,
            customer_phone=phone,
            status="pending_ewash_confirmation",
            customer_name="Test Customer",
            vehicle_type="Citadine",
            car_model="Clio",
            color="Bleu",
            service_id="svc_ext",
            service_label="Lavage extérieur",
            location_mode=location_mode,
            center="Ewash Bouskoura",
            location_name="Ewash Bouskoura",
            address="Rue privée 123",
            address_text="Rue privée 123",
            location_address="Rue privée 123, Bouskoura",
            latitude=33.4,
            longitude=-7.6,
            appointment_date=appointment_date,
            date_label="Aujourd'hui",
            slot_id=slot_id,
            slot="10:00-12:00",
            note="Sonnez au portail",
            total_price_dh=90,
            raw_booking_json='{"address":"Rue privée 123"}',
            created_at=created_at,
        )
    )


def test_mint_customer_token_returns_plaintext_and_stores_hash() -> None:
    engine, phone = _engine_with_customer()

    plaintext = mint_customer_token(phone, engine=engine)

    assert isinstance(plaintext, str) and len(plaintext) >= 32
    # The DB has the SHA-256 hex of plaintext, NOT plaintext itself.
    with session_scope(engine) as session:
        row = session.scalar(select(CustomerTokenRow))
        assert row is not None
        assert row.token_hash == hash_token(plaintext)
        assert row.token_hash != plaintext  # privacy invariant
        assert row.customer_phone == phone
        assert row.last_used_at is None


def test_mint_customer_token_each_call_is_distinct() -> None:
    engine, phone = _engine_with_customer()

    a = mint_customer_token(phone, engine=engine)
    b = mint_customer_token(phone, engine=engine)

    assert a != b
    with session_scope(engine) as session:
        rows = session.scalars(select(CustomerTokenRow)).all()
        assert len(rows) == 2
        # Same phone owns both — multiple tokens per phone are allowed by design.
        assert {row.customer_phone for row in rows} == {phone}


def test_mint_customer_token_without_engine_still_returns_plaintext() -> None:
    # DB-absent path: helper returns plaintext so the API response shape stays
    # well-formed. The subsequent verify call (also DB-less) will then 401.
    plaintext = mint_customer_token("212600000101", engine=None)
    assert isinstance(plaintext, str)
    assert len(plaintext) >= 32


def test_verify_customer_token_returns_phone_for_valid_token() -> None:
    engine, phone = _engine_with_customer()
    plaintext = mint_customer_token(phone, engine=engine)

    result = verify_customer_token(plaintext, engine=engine)

    assert result == phone


def test_verify_customer_token_returns_none_for_unknown_token() -> None:
    engine, _ = _engine_with_customer()
    assert verify_customer_token("not-a-real-token", engine=engine) is None


def test_verify_customer_token_returns_none_for_empty_or_missing_input() -> None:
    engine, _ = _engine_with_customer()
    assert verify_customer_token("", engine=engine) is None
    assert verify_customer_token(None, engine=engine) is None


def test_verify_customer_token_rejects_mismatched_expected_phone() -> None:
    # Defends against token theft: an attacker who steals a token cannot
    # use it to attribute new bookings to a different phone.
    engine, phone = _engine_with_customer()
    plaintext = mint_customer_token(phone, engine=engine)

    result = verify_customer_token(
        plaintext, expected_phone="212600000999", engine=engine,
    )

    assert result is None


def test_verify_customer_token_accepts_matching_expected_phone() -> None:
    engine, phone = _engine_with_customer()
    plaintext = mint_customer_token(phone, engine=engine)

    result = verify_customer_token(plaintext, expected_phone=phone, engine=engine)

    assert result == phone


def test_verify_customer_token_bumps_last_used_at() -> None:
    engine, phone = _engine_with_customer()
    before = datetime.now(timezone.utc)
    plaintext = mint_customer_token(phone, engine=engine)

    verify_customer_token(plaintext, engine=engine)

    with session_scope(engine) as session:
        row = session.scalar(select(CustomerTokenRow))
        assert row.last_used_at is not None
        # Normalize tz: SQLite stores naive datetimes; treat as UTC for comparison.
        last_used = (
            row.last_used_at if row.last_used_at.tzinfo is not None
            else row.last_used_at.replace(tzinfo=timezone.utc)
        )
        assert last_used >= before


def test_verify_customer_token_does_not_bump_last_used_at_on_miss() -> None:
    engine, phone = _engine_with_customer()
    mint_customer_token(phone, engine=engine)

    verify_customer_token("definitely-wrong-token", engine=engine)

    with session_scope(engine) as session:
        row = session.scalar(select(CustomerTokenRow))
        assert row.last_used_at is None


def test_verify_customer_token_without_engine_returns_none() -> None:
    # DB-absent path: verify cannot prove ownership, so the helper rejects.
    assert verify_customer_token("any-token", engine=None) is None


def test_mint_and_verify_roundtrip_is_collision_resistant() -> None:
    # Belt-and-suspenders: 100 distinct mint calls should all verify uniquely.
    engine, phone = _engine_with_customer()
    plaintexts = [mint_customer_token(phone, engine=engine) for _ in range(100)]
    assert len(set(plaintexts)) == 100
    for plaintext in plaintexts:
        assert verify_customer_token(plaintext, engine=engine) == phone


def test_token_hash_is_64_hex_chars() -> None:
    # Migration 0006 declares VARCHAR(64). Confirm the column always fits.
    engine, phone = _engine_with_customer()
    mint_customer_token(phone, engine=engine)
    with session_scope(engine) as session:
        row = session.scalar(select(CustomerTokenRow))
        assert len(row.token_hash) == 64
        assert all(ch in "0123456789abcdef" for ch in row.token_hash)


def test_list_bookings_for_token_returns_empty_for_unknown_or_missing_token() -> None:
    engine, _ = _engine_with_customer()

    assert list_bookings_for_token(None, engine=engine) == ([], None)
    assert list_bookings_for_token("", engine=engine) == ([], None)
    assert list_bookings_for_token("not-a-real-token", engine=engine) == ([], None)
    assert list_bookings_for_token("not-a-real-token", engine=None) == ([], None)


def test_list_bookings_for_token_limits_and_sorts_recent_first() -> None:
    engine, phone = _engine_with_customer()
    other_phone = "212600000999"
    now = datetime.now(timezone.utc)
    with session_scope(engine) as session:
        session.add(Customer(phone=other_phone, display_name="Other"))
        _add_booking(session, phone=phone, ref="EW-2026-0001", created_at=now - timedelta(days=2))
        _add_booking(session, phone=phone, ref="EW-2026-0002", created_at=now)
        _add_booking(session, phone=phone, ref="EW-2026-0003", created_at=now - timedelta(days=1))
        _add_booking(session, phone=other_phone, ref="EW-2026-9999", created_at=now + timedelta(days=1))
    token = mint_customer_token(phone, engine=engine)

    items, next_cursor = list_bookings_for_token(token, limit=2, engine=engine)

    assert [item["ref"] for item in items] == ["EW-2026-0002", "EW-2026-0003"]
    assert next_cursor is not None


def test_list_bookings_for_token_projects_safe_field_whitelist() -> None:
    engine, phone = _engine_with_customer()
    with session_scope(engine) as session:
        _add_booking(
            session,
            phone=phone,
            ref="EW-2026-0001",
            created_at=datetime.now(timezone.utc),
            location_mode="home",
        )
    token = mint_customer_token(phone, engine=engine)

    items, _next_cursor = list_bookings_for_token(token, engine=engine)
    item = items[0]

    assert set(item) == {
        "ref",
        "status",
        "status_label",
        "service_label",
        "service_id",
        "vehicle_label",
        "date_iso",
        "date_label",
        "slot_id",
        "slot_label",
        "slot_start_hour",
        "slot_end_hour",
        "location_label",
        "total_price_dh",
        "created_at",
    }
    assert item["status_label"] == "À confirmer par eWash"
    assert item["location_label"] == "À domicile"
    assert item["total_price_dh"] == 90
    for forbidden in (
        "address",
        "address_text",
        "location_address",
        "latitude",
        "longitude",
        "note",
        "raw_booking_json",
    ):
        assert forbidden not in item


def test_list_bookings_for_token_populates_structured_date_and_slot() -> None:
    engine, phone = _engine_with_customer()
    with session_scope(engine) as session:
        _add_booking(
            session,
            phone=phone,
            ref="EW-2026-0001",
            created_at=datetime.now(timezone.utc),
            appointment_date=date(2026, 5, 20),
            slot_id="slot_10_12",
        )
    token = mint_customer_token(phone, engine=engine)

    items, _next_cursor = list_bookings_for_token(token, engine=engine)
    item = items[0]

    assert item["service_id"] == "svc_ext"
    assert item["date_iso"] == "2026-05-20"
    assert item["slot_id"] == "slot_10_12"
    assert item["slot_start_hour"] == 10
    assert item["slot_end_hour"] == 12


def test_list_bookings_for_token_unparseable_slot_hours_fallback() -> None:
    engine, phone = _engine_with_customer()
    with session_scope(engine) as session:
        _add_booking(
            session,
            phone=phone,
            ref="EW-2026-0001",
            created_at=datetime.now(timezone.utc),
            slot_id="weird_id",
        )
    token = mint_customer_token(phone, engine=engine)

    items, _next_cursor = list_bookings_for_token(token, engine=engine)
    item = items[0]

    assert item["slot_start_hour"] == 0
    assert item["slot_end_hour"] == 0


def test_customer_booking_view_status_label_covers_all_booking_statuses() -> None:
    for status in BOOKING_STATUSES:
        row = BookingRow(
            ref=f"EW-2026-{BOOKING_STATUSES.index(status) + 1:04d}",
            customer_phone="212600000100",
            status=status,
            service_label="Lavage extérieur",
            service_id="svc_ext",
            vehicle_type="Citadine",
            date_label="Aujourd'hui",
            slot="10:00-12:00",
            total_price_dh=90,
            created_at=datetime.now(timezone.utc),
        )

        view = _to_customer_view(row)

        assert view["status_label"]
        assert view["status_label"] != f"status.{status}"


def test_customer_booking_view_date_iso_empty_without_appointment_date() -> None:
    row = BookingRow(
        ref="EW-2026-0001",
        customer_phone="212600000100",
        status="confirmed",
        appointment_date=None,
    )

    view = _to_customer_view(row)

    assert view["date_iso"] == ""
