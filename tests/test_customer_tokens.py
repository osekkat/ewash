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

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db import init_db, make_engine, session_scope
from app.models import Customer, CustomerTokenRow
from app.persistence import mint_customer_token, verify_customer_token
from app.security import hash_token


def _engine_with_customer(phone: str = "212600000100"):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    with session_scope(engine) as session:
        session.add(Customer(phone=phone, display_name="Test"))
    return engine, phone


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
