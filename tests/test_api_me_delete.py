"""Smoke tests for DELETE /api/v1/me — customer-initiated data erasure.

These cover the contract surface: authentication, confirm-phrase enforcement,
and the happy-path side effects (customer-side rows deleted, bookings
anonymized, audit row written). The exhaustive 8-test suite for compliance
regression coverage lives in `tests/test_api_me_delete.py` under bead
``ewash-6pa.7.19`` (separate test bead) — keep this file focused on what's
necessary to prove the route works without duplicating that work.
"""
from __future__ import annotations

import logging
from unittest import TestCase

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select

from app import api, persistence
from app.booking import Booking
from app.config import settings
from app.db import init_db, make_engine, session_scope
from app.models import (
    BookingRow,
    Customer,
    CustomerName,
    CustomerTokenRow,
    DataErasureAuditRow,
)
from app.persistence import mint_customer_token, persist_confirmed_booking
from app.rate_limit import limiter

case = TestCase()

CONFIRM_PHRASE = "I confirm I want to delete my data"


def _client(*, raise_server_exceptions: bool = True) -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api.router)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    api.install_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


@pytest.fixture
def api_db(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'api-me-delete.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    persistence._configured_engine.cache_clear()
    limiter.reset()
    try:
        yield engine
    finally:
        persistence._configured_engine.cache_clear()
        limiter.reset()


def _seed_customer(engine, phone: str) -> None:
    with session_scope(engine) as session:
        session.add(Customer(phone=phone, display_name="Hassan El"))


def _seed_booking(engine, *, phone: str, ref: str) -> None:
    """Create a confirmed booking row with realistic PII so anonymization has
    visible work to do. Uses the production persistence path so the row
    matches what the API would actually write."""
    booking = Booking(phone=phone)
    booking.name = "Hassan El"
    booking.category = "B"
    booking.vehicle_type = "B — Berline / SUV"
    booking.car_model = "BMW 330i"
    booking.color = "Noir"
    booking.service = "svc_cpl"
    booking.service_bucket = "wash"
    booking.service_label = "Le Complet — 125 DH"
    booking.price_dh = 125
    booking.price_regular_dh = 125
    booking.location_mode = "home"
    booking.location_address = "Bouskoura, portail bleu"
    booking.address = "Bouskoura, portail bleu, sonner deux fois"
    booking.note = "Garé devant le garage"
    booking.date_iso = "2026-06-15"
    booking.date_label = "Lundi 15 juin 2026"
    booking.slot_id = "slot_9_11"
    booking.slot = "09h – 11h"
    booking.ref = ref
    row = persist_confirmed_booking(booking, engine=engine, source="api")
    assert row is not None


def test_delete_me_requires_token(api_db):
    with _client() as client:
        response = client.request(
            "DELETE",
            "/api/v1/me",
            json={"confirm": CONFIRM_PHRASE},
        )

    case.assertEqual(response.status_code, 401)
    case.assertEqual(response.json()["error_code"], "missing_token")
    case.assertEqual(response.headers["X-Ewash-Error-Code"], "missing_token")


def test_delete_me_requires_valid_token(api_db):
    with _client() as client:
        response = client.request(
            "DELETE",
            "/api/v1/me",
            json={"confirm": CONFIRM_PHRASE},
            headers={"X-Ewash-Token": "not-a-real-token"},
        )

    case.assertEqual(response.status_code, 401)
    case.assertEqual(response.json()["error_code"], "invalid_token")
    case.assertEqual(response.headers["X-Ewash-Error-Code"], "invalid_token")


def test_delete_me_rejects_wrong_confirm_phrase_with_422(api_db):
    phone = "212600000500"
    _seed_customer(api_db, phone)
    token = mint_customer_token(phone, engine=api_db)

    with _client() as client:
        # Pydantic ``Literal`` rejects anything that is not the exact phrase.
        response = client.request(
            "DELETE",
            "/api/v1/me",
            json={"confirm": "yes please"},
            headers={"X-Ewash-Token": token},
        )

    case.assertEqual(response.status_code, 422)
    # The token survives — a 422 must not have side effects.
    case.assertEqual(persistence.verify_customer_token(token, engine=api_db), phone)


def test_delete_me_happy_path_purges_tokens_and_anonymizes_bookings(api_db):
    phone = "212600000501"
    _seed_customer(api_db, phone)
    persistence.persist_customer_name(phone, "Hassan El", engine=api_db)
    _seed_booking(api_db, phone=phone, ref="EW-2026-7001")
    _seed_booking(api_db, phone=phone, ref="EW-2026-7002")
    token = mint_customer_token(phone, engine=api_db)
    other_token = mint_customer_token(phone, engine=api_db)

    with _client() as client:
        response = client.request(
            "DELETE",
            "/api/v1/me",
            json={"confirm": CONFIRM_PHRASE},
            headers={"X-Ewash-Token": token},
        )

    case.assertEqual(response.status_code, 200)
    body = response.json()
    # The 2 bookings worth of anonymization, plus the customer-side rows that
    # were created above: 2 tokens + 1 customer_names + 1 customer_vehicle (auto-
    # created during persist_confirmed_booking). Compare loosely — the exact
    # number depends on `persist_confirmed_booking` side effects we don't want
    # to overspecify in a smoke test.
    case.assertEqual(body["anonymized_bookings"], 2)
    case.assertGreaterEqual(body["deleted_count"], 2)  # at least both tokens

    # Both tokens for this phone are gone.
    case.assertIsNone(persistence.verify_customer_token(token, engine=api_db))
    case.assertIsNone(persistence.verify_customer_token(other_token, engine=api_db))

    # Customer-side identifying records gone.
    with session_scope(api_db) as session:
        tokens = session.scalars(
            select(CustomerTokenRow).where(CustomerTokenRow.customer_phone == phone)
        ).all()
        names = session.scalars(
            select(CustomerName).where(CustomerName.customer_phone == phone)
        ).all()
        # Bookings: rows still exist but PII is scrubbed and customer_phone
        # was rewritten to the anonymized value.
        bookings = session.scalars(select(BookingRow)).all()

    case.assertEqual(tokens, [])
    case.assertEqual(names, [])
    case.assertEqual(len(bookings), 2)
    for booking_row in bookings:
        case.assertTrue(booking_row.customer_phone.startswith("DEL-"))
        case.assertNotEqual(booking_row.customer_phone, phone)
        case.assertEqual(booking_row.customer_name, "Anonyme")
        case.assertEqual(booking_row.car_model, "")
        case.assertEqual(booking_row.color, "")
        case.assertEqual(booking_row.note, "")
        case.assertEqual(booking_row.address, "")
        case.assertEqual(booking_row.raw_booking_json, "{}")


def test_delete_me_writes_audit_row(api_db):
    phone = "212600000502"
    _seed_customer(api_db, phone)
    token = mint_customer_token(phone, engine=api_db)

    with _client() as client:
        client.request(
            "DELETE",
            "/api/v1/me",
            json={"confirm": CONFIRM_PHRASE},
            headers={"X-Ewash-Token": token},
        )

    with session_scope(api_db) as session:
        audits = session.scalars(select(DataErasureAuditRow)).all()

    case.assertEqual(len(audits), 1)
    audit = audits[0]
    case.assertEqual(audit.actor, "customer_self_serve")
    # phone_hash is the full SHA-256 hex (64 chars), NEVER the plaintext phone.
    case.assertEqual(len(audit.phone_hash), 64)
    case.assertNotIn(phone, audit.phone_hash)


def test_post_delete_token_returns_401(api_db):
    """The token used to authorize the deletion must itself be revoked, so a
    subsequent request with the same token gets the same envelope shape as a
    completely unknown token."""
    phone = "212600000503"
    _seed_customer(api_db, phone)
    token = mint_customer_token(phone, engine=api_db)

    with _client() as client:
        first = client.request(
            "DELETE",
            "/api/v1/me",
            json={"confirm": CONFIRM_PHRASE},
            headers={"X-Ewash-Token": token},
        )
        case.assertEqual(first.status_code, 200)

        # Using the now-deleted token elsewhere returns invalid_token.
        second = client.get(
            "/api/v1/bookings",
            headers={"X-Ewash-Token": token},
        )

    case.assertEqual(second.status_code, 401)
    case.assertEqual(second.json()["error_code"], "invalid_token")


def test_delete_me_emits_structured_log_line(api_db, caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")
    phone = "212600000504"
    _seed_customer(api_db, phone)
    token = mint_customer_token(phone, engine=api_db)

    with _client() as client:
        client.request(
            "DELETE",
            "/api/v1/me",
            json={"confirm": CONFIRM_PHRASE},
            headers={"X-Ewash-Token": token},
        )

    matches = [r.getMessage() for r in caplog.records if "me.delete" in r.getMessage()]
    case.assertTrue(matches, msg=f"no me.delete log captured; got {[r.getMessage() for r in caplog.records]}")
    success_lines = [m for m in matches if "phone_hash=" in m and "deleted_count=" in m]
    case.assertTrue(success_lines)
    line = success_lines[0]
    case.assertNotIn(phone, line)
    case.assertIn("anonymized_bookings=", line)
