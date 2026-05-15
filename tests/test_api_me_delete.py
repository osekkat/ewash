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
    ConversationSessionRow,
    Customer,
    CustomerName,
    CustomerTokenRow,
    CustomerVehicle,
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


# ─────────────────────────────────────────────────────────────────────────────
# Compliance-grade per-table purge + cross-customer isolation + rate limit.
# These extend the smoke-test set above to cover every customer-side table the
# erasure helper touches, plus the contracts that matter for Loi 09-08 / GDPR
# regression testing.
# ─────────────────────────────────────────────────────────────────────────────


def test_delete_me_purges_customer_vehicles_for_phone(api_db):
    """``persist_confirmed_booking`` auto-creates a ``customer_vehicles`` row.
    The erasure path must remove it so the make/color/plate combination can no
    longer be linked to the customer."""
    phone = "212600000510"
    _seed_customer(api_db, phone)
    _seed_booking(api_db, phone=phone, ref="EW-2026-7100")
    token = mint_customer_token(phone, engine=api_db)

    with session_scope(api_db) as session:
        vehicles_before = session.scalars(
            select(CustomerVehicle).where(CustomerVehicle.customer_phone == phone)
        ).all()
    case.assertGreater(
        len(vehicles_before),
        0,
        msg="setup precondition: persist_confirmed_booking should have created a customer_vehicles row",
    )

    with _client() as client:
        response = client.request(
            "DELETE",
            "/api/v1/me",
            json={"confirm": CONFIRM_PHRASE},
            headers={"X-Ewash-Token": token},
        )
    case.assertEqual(response.status_code, 200)

    with session_scope(api_db) as session:
        vehicles_after = session.scalars(
            select(CustomerVehicle).where(CustomerVehicle.customer_phone == phone)
        ).all()
    case.assertEqual(vehicles_after, [])


def test_delete_me_purges_conversation_sessions_for_phone(api_db):
    """Conversation sessions (and any FK-chained events) must be deleted so the
    customer's WhatsApp state trail is also erased."""
    phone = "212600000511"
    _seed_customer(api_db, phone)
    with session_scope(api_db) as session:
        # ``_seed_customer`` above already inserted the customers row for this
        # phone; ConversationSessionRow only needs the FK to satisfy.
        session.add(
            ConversationSessionRow(
                customer_phone=phone,
                current_stage="MENU",
            )
        )
    token = mint_customer_token(phone, engine=api_db)

    with _client() as client:
        client.request(
            "DELETE",
            "/api/v1/me",
            json={"confirm": CONFIRM_PHRASE},
            headers={"X-Ewash-Token": token},
        )

    with session_scope(api_db) as session:
        sessions = session.scalars(
            select(ConversationSessionRow).where(ConversationSessionRow.customer_phone == phone)
        ).all()
    case.assertEqual(sessions, [])


def test_delete_me_does_not_affect_other_customers(api_db):
    """The deletion is strictly scoped to the calling token's phone. A
    different customer's tokens, names, vehicles and booking PII must survive
    untouched — a regression here would be a multi-customer data wipe."""
    target_phone = "212600000512"
    other_phone = "212600000513"
    _seed_customer(api_db, target_phone)
    _seed_customer(api_db, other_phone)
    persistence.persist_customer_name(other_phone, "Hassan Other", engine=api_db)
    _seed_booking(api_db, phone=other_phone, ref="EW-2026-7200")
    other_token = mint_customer_token(other_phone, engine=api_db)
    target_token = mint_customer_token(target_phone, engine=api_db)

    with _client() as client:
        response = client.request(
            "DELETE",
            "/api/v1/me",
            json={"confirm": CONFIRM_PHRASE},
            headers={"X-Ewash-Token": target_token},
        )
    case.assertEqual(response.status_code, 200)

    # Other customer untouched.
    case.assertEqual(persistence.verify_customer_token(other_token, engine=api_db), other_phone)
    with session_scope(api_db) as session:
        other_names = session.scalars(
            select(CustomerName).where(CustomerName.customer_phone == other_phone)
        ).all()
        other_bookings = session.scalars(
            select(BookingRow).where(BookingRow.customer_phone == other_phone)
        ).all()
        other_vehicles = session.scalars(
            select(CustomerVehicle).where(CustomerVehicle.customer_phone == other_phone)
        ).all()

    # ``persist_confirmed_booking`` upserts its own ``customer_names`` entry
    # alongside the explicit ``persist_customer_name`` call, so the row count
    # is at least 1 — both rows belong to the OTHER customer and must survive.
    case.assertGreaterEqual(len(other_names), 1)
    case.assertEqual(len(other_bookings), 1)
    case.assertEqual(other_bookings[0].customer_phone, other_phone)
    # The booking was seeded with name "Hassan El" by ``_seed_booking``; what
    # matters here is that the row WASN'T anonymized — the name is not the
    # "Anonyme" sentinel and the customer_phone wasn't pivoted to a DEL-prefix.
    case.assertNotEqual(other_bookings[0].customer_name, "Anonyme")
    case.assertFalse(other_bookings[0].customer_phone.startswith("DEL-"))
    case.assertGreater(len(other_vehicles), 0)


def test_delete_me_log_phone_hash_matches_audit_row_phone_hash(api_db, caplog):
    """The log line emits ``phone_hash=<sha256[:12]>`` while the audit row
    stores the full 64-char digest. The two MUST share a prefix so an admin
    investigating a log line can pivot to the corresponding audit entry."""
    caplog.set_level(logging.INFO, logger="ewash.api")
    phone = "212600000514"
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
        audit = session.scalars(select(DataErasureAuditRow)).one()

    log_lines = [
        rec.getMessage()
        for rec in caplog.records
        if "me.delete" in rec.getMessage() and "phone_hash=" in rec.getMessage()
    ]
    case.assertTrue(log_lines)
    # Extract the 12-char hash printed by `_hash_for_log` in the log line.
    line = log_lines[0]
    marker = "phone_hash="
    start = line.index(marker) + len(marker)
    # Tokens in the log line are space-separated.
    log_hash = line[start:].split(" ", 1)[0]
    case.assertEqual(len(log_hash), 12)
    case.assertTrue(
        audit.phone_hash.startswith(log_hash),
        msg=f"log hash {log_hash!r} is not a prefix of audit hash {audit.phone_hash!r}",
    )


def test_delete_me_rate_limited(api_db):
    """3/hour per token per the bead spec. Hit the route 3 times with the same
    token (first succeeds, 2nd/3rd would 401 since the token is revoked but
    still consume the limiter bucket) then prove the 4th call 429s."""
    phone = "212600000515"
    _seed_customer(api_db, phone)
    token = mint_customer_token(phone, engine=api_db)

    with _client() as client:
        for i in range(3):
            response = client.request(
                "DELETE",
                "/api/v1/me",
                json={"confirm": CONFIRM_PHRASE},
                headers={"X-Ewash-Token": token},
            )
            case.assertNotEqual(
                response.status_code,
                429,
                msg=f"unexpected 429 on attempt {i + 1}",
            )

        burst = client.request(
            "DELETE",
            "/api/v1/me",
            json={"confirm": CONFIRM_PHRASE},
            headers={"X-Ewash-Token": token},
        )

    case.assertEqual(burst.status_code, 429)
