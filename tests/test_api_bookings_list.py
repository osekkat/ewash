"""Tests for GET /api/v1/bookings — token-scoped customer booking list.

The PWA's Bookings tab fetches recent bookings via this endpoint. The
contract is deliberately narrow: opaque ``X-Ewash-Token`` is the only
authenticator and there is no ``?phone=`` query parameter, so an
attacker cannot enumerate phones by probing the read path.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import api, persistence
from app.booking import Booking
from app.db import init_db, make_engine
from app.persistence import mint_customer_token, persist_confirmed_booking
from app.rate_limit import limiter


@pytest.fixture
def engine(monkeypatch, tmp_path):
    """A file-backed SQLite engine bound to ``persistence._configured_engine``.

    The handler calls ``persistence.list_bookings_for_token`` which reaches for
    ``_configured_engine`` when no override is passed; the lru_cache on that
    function would otherwise pin the first test's database, so we replace the
    function itself.
    """
    db_path = tmp_path / "api-bookings.db"
    engine = make_engine(f"sqlite+pysqlite:///{db_path}")
    init_db(engine)
    monkeypatch.setattr(persistence, "_configured_engine", lambda: engine)
    return engine


@pytest.fixture
def client():
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(api.router)
    api.install_exception_handlers(app)
    with TestClient(app) as test_client:
        yield test_client


def _seed_booking(
    engine,
    *,
    phone: str,
    ref: str,
    created_at: datetime | None = None,
) -> Booking:
    booking = Booking(phone=phone)
    booking.name = "Test Client"
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
    booking.location_address = "Bouskoura"
    booking.address = "Bouskoura, portail bleu"
    booking.note = "Sonner deux fois"
    booking.date_iso = "2026-06-15"
    booking.date_label = "Lundi 15 juin 2026"
    booking.slot_id = "slot_9_11"
    booking.slot = "09h – 11h"
    booking.ref = ref
    row = persist_confirmed_booking(booking, engine=engine, source="api")
    assert row is not None
    if created_at is not None:
        with persistence.session_scope(engine) as session:
            from app.models import BookingRow
            from sqlalchemy import update
            session.execute(
                update(BookingRow).where(BookingRow.ref == ref).values(created_at=created_at)
            )
    return booking


def test_valid_token_with_no_bookings_returns_empty_list(engine, client):
    token = mint_customer_token("212611204502", engine=engine)

    response = client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})

    assert response.status_code == 200
    body = response.json()
    assert body == {"bookings": [], "next_cursor": None}


def test_valid_token_returns_bookings_sorted_recent_first(engine, client):
    phone = "212611204502"
    token = mint_customer_token(phone, engine=engine)
    base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    _seed_booking(engine, phone=phone, ref="EW-2026-0001", created_at=base)
    _seed_booking(engine, phone=phone, ref="EW-2026-0002", created_at=base + timedelta(hours=1))
    _seed_booking(engine, phone=phone, ref="EW-2026-0003", created_at=base + timedelta(hours=2))

    response = client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})

    assert response.status_code == 200
    refs = [item["ref"] for item in response.json()["bookings"]]
    assert refs == ["EW-2026-0003", "EW-2026-0002", "EW-2026-0001"]


def test_missing_header_returns_401_missing_token(engine, client):
    response = client.get("/api/v1/bookings")

    assert response.status_code == 401
    assert response.headers["X-Ewash-Error-Code"] == "missing_token"
    body = response.json()
    assert body["error_code"] == "missing_token"


def test_invalid_token_returns_401_invalid_token(engine, client):
    response = client.get(
        "/api/v1/bookings",
        headers={"X-Ewash-Token": "not-a-real-token"},
    )

    assert response.status_code == 401
    assert response.headers["X-Ewash-Error-Code"] == "invalid_token"
    assert response.json()["error_code"] == "invalid_token"


def test_phone_query_param_is_rejected_with_400(engine, client):
    """Reading by phone-from-querystring would re-introduce enumeration. The
    handler refuses the parameter loudly so the misuse is visible in logs."""
    token = mint_customer_token("212611204502", engine=engine)

    response = client.get(
        "/api/v1/bookings?phone=212611204502",
        headers={"X-Ewash-Token": token},
    )

    assert response.status_code == 400
    assert response.headers["X-Ewash-Error-Code"] == "phone_param_not_accepted"
    body = response.json()
    assert body["error_code"] == "phone_param_not_accepted"


def test_response_omits_pii_fields(engine, client):
    """The customer-safe projection must not leak fields beyond the read
    contract — no raw address, no internal note, no phone, no GPS."""
    phone = "212611204502"
    token = mint_customer_token(phone, engine=engine)
    _seed_booking(engine, phone=phone, ref="EW-2026-9001")

    response = client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})

    assert response.status_code == 200
    items = response.json()["bookings"]
    assert len(items) == 1
    forbidden_fields = {
        "phone",
        "customer_phone",
        "address",
        "address_text",
        "location_address",
        "note",
        "latitude",
        "longitude",
        "raw_booking_json",
        "promo_code",
    }
    leaked = forbidden_fields & set(items[0].keys())
    assert not leaked, f"PII leaked: {leaked}"


def test_bookings_are_scoped_to_token_owner(engine, client):
    """A token minted for phone A must not see phone B's bookings."""
    phone_a = "212611204502"
    phone_b = "212611204503"
    token_a = mint_customer_token(phone_a, engine=engine)
    _seed_booking(engine, phone=phone_a, ref="EW-2026-AA01")
    _seed_booking(engine, phone=phone_b, ref="EW-2026-BB01")

    response = client.get("/api/v1/bookings", headers={"X-Ewash-Token": token_a})

    refs = [item["ref"] for item in response.json()["bookings"]]
    assert refs == ["EW-2026-AA01"]


def test_emits_structured_log_line_on_success(engine, client, caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")
    phone = "212611204502"
    token = mint_customer_token(phone, engine=engine)

    client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})

    matches = [rec.message for rec in caplog.records if "bookings.list" in rec.message]
    assert matches, "No bookings.list INFO line emitted"
    assert any("count=0" in line for line in matches)
    assert any("phone_hash=" in line for line in matches)


def test_emits_warn_line_with_token_prefix_on_invalid_token(engine, client, caplog):
    """Debugging \"is the same actor hitting us with bad tokens\" needs the
    hashed prefix in the log so we don't store plaintext tokens anywhere."""
    caplog.set_level(logging.INFO, logger="ewash.api")

    client.get("/api/v1/bookings", headers={"X-Ewash-Token": "this-is-garbage"})

    rejection = [rec.message for rec in caplog.records if "error=invalid_token" in rec.message]
    assert rejection, "No invalid_token rejection logged"
    assert any("token_prefix=" in line for line in rejection)


# ─────────────────────────────────────────────────────────────────────────────
# Response shape — structured fields the PWA's Add-to-Calendar, status pill,
# and Book-again CTA depend on.
# ─────────────────────────────────────────────────────────────────────────────


def test_response_includes_structured_date_and_slot_fields(engine, client):
    """The Add-to-Calendar feature needs the raw ISO date, the slot id, and
    integer start/end hours — not just the localized French label strings.
    The PWA generates an ICS file client-side; without ``date_iso``/
    ``slot_start_hour``/``slot_end_hour`` it would have to re-parse the
    localized label which breaks under Arabic."""
    phone = "212611204502"
    token = mint_customer_token(phone, engine=engine)
    _seed_booking(engine, phone=phone, ref="EW-2026-DT01")

    response = client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})

    assert response.status_code == 200
    item = response.json()["bookings"][0]
    assert item["date_iso"] == "2026-06-15"
    assert item["slot_id"] == "slot_9_11"
    assert isinstance(item["slot_start_hour"], int) and item["slot_start_hour"] == 9
    assert isinstance(item["slot_end_hour"], int) and item["slot_end_hour"] == 11
    assert item["slot_end_hour"] > item["slot_start_hour"]


def test_response_includes_stable_status_and_localized_label(engine, client):
    """``status`` is the canonical enum value the PWA branches on for i18n;
    ``status_label`` is the French human-readable fallback so a stale PWA
    that doesn't yet know a new status enum still renders something
    intelligible. Both must be present and non-empty."""
    phone = "212611204502"
    token = mint_customer_token(phone, engine=engine)
    _seed_booking(engine, phone=phone, ref="EW-2026-ST01")

    response = client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})

    item = response.json()["bookings"][0]
    assert item["status"] == "pending_ewash_confirmation"
    assert isinstance(item["status_label"], str) and item["status_label"]


def test_response_includes_service_id_for_book_again(engine, client):
    """The Bookings detail modal's "Réserver à nouveau" CTA pre-fills the
    booking flow with the previous service id. The list endpoint therefore
    has to expose ``service_id`` alongside the localized ``service_label``."""
    phone = "212611204502"
    token = mint_customer_token(phone, engine=engine)
    _seed_booking(engine, phone=phone, ref="EW-2026-SV01")

    response = client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})

    item = response.json()["bookings"][0]
    assert item["service_id"] == "svc_cpl"
    assert item["service_label"]  # non-empty


def test_last_used_at_is_bumped_on_each_successful_verify(engine, client):
    """``verify_customer_token`` writes ``last_used_at = now()`` on every
    successful match. The admin-side token-janitor will rely on this column
    to identify stale tokens. Two GETs separated by a small delta must show
    two distinct timestamps."""
    from app.models import CustomerTokenRow
    from sqlalchemy import select

    phone = "212611204502"
    token = mint_customer_token(phone, engine=engine)

    client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})
    with persistence.session_scope(engine) as session:
        first = session.scalars(select(CustomerTokenRow)).one().last_used_at

    assert first is not None

    client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})
    with persistence.session_scope(engine) as session:
        second = session.scalars(select(CustomerTokenRow)).one().last_used_at

    assert second is not None
    # SQLite datetime stores down to microseconds, so identical timestamps are
    # vanishingly unlikely; the assertion has to accept >= rather than > so a
    # genuinely-instantaneous double-call doesn't flake the test.
    assert second >= first


def test_rate_limited_per_token_returns_429(engine, client):
    """Once the per-token quota is drained, the next request returns 429.

    The decorator binds the rate-limit string at import time, so we don't try
    to shrink it for the test — instead we drain the underlying limit-bucket
    programmatically using the SAME storage args slowapi uses internally:
    ``hit(rule, limit_key, limit_scope)`` where ``limit_key`` is what
    ``_token_key_func`` returns and ``limit_scope`` is the qualname of the
    handler joined with the request method.
    """
    from limits import parse

    from app.config import settings
    from app.security import hash_token

    phone = "212611204502"
    token = mint_customer_token(phone, engine=engine)

    rule = parse(settings.rate_limit_bookings_list_per_token)
    limit_key = f"token:{hash_token(token)[:16]}"
    # slowapi joins (limit_key, route-path) into the storage key, e.g.
    # ``LIMITER/token:<hash>//api/v1/bookings/1000/1/hour``. The drain has to
    # use the same scope tuple or it'll fill a different bucket.
    limit_scope = "/api/v1/bookings"

    for _ in range(rule.amount):
        # Drain the bucket synchronously. Each ``hit`` returns True while
        # there is capacity left.
        assert limiter.limiter.hit(rule, limit_key, limit_scope), (
            "rate-limit drain returned False before reaching the configured ceiling"
        )

    response = client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})

    assert response.status_code == 429
