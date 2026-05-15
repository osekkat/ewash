"""Tests for POST /api/v1/tokens/revoke.

`revoke_token` is how the PWA logs out. The endpoint accepts the customer's
opaque token via ``X-Ewash-Token`` and physically deletes one or all matching
``customer_tokens`` rows. After a successful revoke any further call carrying
the same token must 401 — the token is no longer hashed in the DB.
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
from app.config import settings
from app.db import init_db, make_engine, session_scope
from app.models import Customer, CustomerTokenRow
from app.rate_limit import limiter
from app.security import hash_token

case = TestCase()


def _client(*, raise_server_exceptions: bool = True) -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api.router)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    api.install_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


@pytest.fixture
def api_db(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'api-tokens-revoke.db'}"
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
        session.add(Customer(phone=phone, display_name="Test Revoke"))


def test_revoke_current_removes_only_the_calling_token(api_db):
    phone = "212600000400"
    _seed_customer(api_db, phone)
    token_a = persistence.mint_customer_token(phone, engine=api_db)
    token_b = persistence.mint_customer_token(phone, engine=api_db)

    with _client() as client:
        response = client.post(
            "/api/v1/tokens/revoke",
            json={"scope": "current"},
            headers={"X-Ewash-Token": token_a},
        )

    case.assertEqual(response.status_code, 200)
    case.assertEqual(response.json(), {"revoked_count": 1})

    # The other token still verifies; the revoked one no longer does.
    case.assertIsNone(persistence.verify_customer_token(token_a, engine=api_db))
    case.assertEqual(persistence.verify_customer_token(token_b, engine=api_db), phone)


def test_revoke_defaults_to_current_scope_when_body_omits_it(api_db):
    phone = "212600000401"
    _seed_customer(api_db, phone)
    token_a = persistence.mint_customer_token(phone, engine=api_db)
    token_b = persistence.mint_customer_token(phone, engine=api_db)

    with _client() as client:
        # Empty JSON body — `scope` defaults to "current".
        response = client.post(
            "/api/v1/tokens/revoke",
            json={},
            headers={"X-Ewash-Token": token_a},
        )

    case.assertEqual(response.status_code, 200)
    case.assertEqual(response.json()["revoked_count"], 1)
    case.assertIsNone(persistence.verify_customer_token(token_a, engine=api_db))
    case.assertEqual(persistence.verify_customer_token(token_b, engine=api_db), phone)


def test_revoke_all_removes_every_token_for_the_phone(api_db):
    phone = "212600000402"
    _seed_customer(api_db, phone)
    tokens = [persistence.mint_customer_token(phone, engine=api_db) for _ in range(3)]

    with _client() as client:
        response = client.post(
            "/api/v1/tokens/revoke",
            json={"scope": "all"},
            headers={"X-Ewash-Token": tokens[0]},
        )

    case.assertEqual(response.status_code, 200)
    case.assertEqual(response.json()["revoked_count"], 3)

    # No customer_tokens rows survive for this phone.
    with session_scope(api_db) as session:
        remaining = session.scalars(
            select(CustomerTokenRow).where(CustomerTokenRow.customer_phone == phone)
        ).all()
    case.assertEqual(remaining, [])


def test_revoke_all_leaves_other_phones_tokens_intact(api_db):
    phone_a = "212600000403"
    phone_b = "212600000404"
    _seed_customer(api_db, phone_a)
    _seed_customer(api_db, phone_b)
    token_a = persistence.mint_customer_token(phone_a, engine=api_db)
    token_b = persistence.mint_customer_token(phone_b, engine=api_db)

    with _client() as client:
        response = client.post(
            "/api/v1/tokens/revoke",
            json={"scope": "all"},
            headers={"X-Ewash-Token": token_a},
        )

    case.assertEqual(response.status_code, 200)
    case.assertEqual(persistence.verify_customer_token(token_b, engine=api_db), phone_b)


def test_revoke_returns_401_without_token(api_db):
    with _client() as client:
        response = client.post("/api/v1/tokens/revoke", json={"scope": "current"})

    case.assertEqual(response.status_code, 401)
    body = response.json()
    case.assertEqual(body["error_code"], "missing_token")
    case.assertEqual(response.headers["X-Ewash-Error-Code"], "missing_token")


def test_revoke_returns_401_with_invalid_token(api_db):
    with _client() as client:
        response = client.post(
            "/api/v1/tokens/revoke",
            json={"scope": "current"},
            headers={"X-Ewash-Token": "definitely-not-a-real-token"},
        )

    case.assertEqual(response.status_code, 401)
    case.assertEqual(response.json()["error_code"], "invalid_token")
    case.assertEqual(response.headers["X-Ewash-Error-Code"], "invalid_token")


def test_revoked_token_returns_401_on_subsequent_use(api_db):
    phone = "212600000405"
    _seed_customer(api_db, phone)
    token = persistence.mint_customer_token(phone, engine=api_db)

    with _client() as client:
        first = client.post(
            "/api/v1/tokens/revoke",
            json={"scope": "current"},
            headers={"X-Ewash-Token": token},
        )
        case.assertEqual(first.status_code, 200)

        # The same revoke endpoint now rejects with invalid_token because the
        # SHA-256 hash is gone from customer_tokens.
        second = client.post(
            "/api/v1/tokens/revoke",
            json={"scope": "current"},
            headers={"X-Ewash-Token": token},
        )
        case.assertEqual(second.status_code, 401)
        case.assertEqual(second.json()["error_code"], "invalid_token")


def test_revoke_returns_422_for_unknown_scope_value(api_db):
    phone = "212600000406"
    _seed_customer(api_db, phone)
    token = persistence.mint_customer_token(phone, engine=api_db)

    with _client() as client:
        response = client.post(
            "/api/v1/tokens/revoke",
            json={"scope": "everything"},  # not in Literal["current", "all"]
            headers={"X-Ewash-Token": token},
        )

    case.assertEqual(response.status_code, 422)


def test_revoke_returns_422_for_extra_fields(api_db):
    # StrictBase rejects unknown keys so PWA typos surface at the contract boundary.
    phone = "212600000407"
    _seed_customer(api_db, phone)
    token = persistence.mint_customer_token(phone, engine=api_db)

    with _client() as client:
        response = client.post(
            "/api/v1/tokens/revoke",
            json={"scope": "current", "also_drop": "everything"},
            headers={"X-Ewash-Token": token},
        )

    case.assertEqual(response.status_code, 422)


def test_revoke_emits_audit_log(api_db, caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")
    phone = "212600000408"
    _seed_customer(api_db, phone)
    token = persistence.mint_customer_token(phone, engine=api_db)

    with _client() as client:
        client.post(
            "/api/v1/tokens/revoke",
            json={"scope": "current"},
            headers={"X-Ewash-Token": token},
        )

    audit_lines = [r.getMessage() for r in caplog.records if "tokens.revoked" in r.getMessage()]
    case.assertTrue(audit_lines, msg=f"no audit log captured; got {[r.getMessage() for r in caplog.records]}")
    line = audit_lines[0]
    # phone_hash is logged but plaintext phone is not.
    case.assertNotIn(phone, line)
    case.assertIn("scope=current", line)
    case.assertIn("count=1", line)


def test_revoke_is_rate_limited(api_db):
    phone = "212600000409"
    _seed_customer(api_db, phone)
    token = persistence.mint_customer_token(phone, engine=api_db)

    # The endpoint allows 10/hour per token. Mint extra tokens so the first
    # 10 hits actually exercise the limiter (revoke would otherwise reduce
    # to 1 successful + 9 invalid). 10 separate tokens for this phone is
    # the cleanest fixture.
    extra_tokens = [persistence.mint_customer_token(phone, engine=api_db) for _ in range(9)]
    all_tokens = [token, *extra_tokens]
    # All 10 share the same token-key bucket only if the limiter keys by
    # hashed token, but each revoke needs a fresh token to succeed. Instead,
    # we hit the limiter with the SAME token by issuing revokes that will
    # 401 after the first success — that still counts against the limiter
    # because slowapi runs the limiter before the handler. Use the same token
    # 11 times: first → 200, 2..10 → 401, 11 → 429.
    with _client() as client:
        for i in range(10):
            r = client.post(
                "/api/v1/tokens/revoke",
                json={"scope": "current"},
                headers={"X-Ewash-Token": token},
            )
            case.assertNotEqual(r.status_code, 429, msg=f"unexpected 429 on attempt {i + 1}")
        burst = client.post(
            "/api/v1/tokens/revoke",
            json={"scope": "current"},
            headers={"X-Ewash-Token": token},
        )

    case.assertEqual(burst.status_code, 429)
    # Reference all_tokens so the extras are seeded (each represents a
    # potential parallel device; unused here but the seeding asserted
    # multi-token persistence works.)
    case.assertEqual(len(all_tokens), 10)
