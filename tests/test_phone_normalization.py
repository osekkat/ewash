"""Tests for app.notifications.normalize_phone — used by WhatsApp + PWA paths."""
from __future__ import annotations

import logging

import pytest

from app.notifications import _normalize_phone_number, normalize_phone


def test_normalize_phone_identity_when_already_clean():
    assert normalize_phone("212611204502") == "212611204502"
    assert normalize_phone("0611204502") == "0611204502"


def test_normalize_phone_strips_internal_whitespace():
    assert normalize_phone("06 11 20 45 02") == "0611204502"


def test_normalize_phone_strips_plus_and_whitespace():
    assert normalize_phone("+212 6 11 20 45 02") == "212611204502"


def test_normalize_phone_strips_dashes_and_parens():
    assert normalize_phone("+1 (212) 555-1234") == "12125551234"


def test_normalize_phone_empty_input_returns_empty():
    # Distinct from short-number rejection: empty/None falls through to "".
    assert normalize_phone("") == ""
    assert normalize_phone(None) == ""


def test_normalize_phone_too_short_raises():
    with pytest.raises(ValueError, match="8-20 digits"):
        normalize_phone("123")


def test_normalize_phone_too_long_raises():
    with pytest.raises(ValueError, match="8-20 digits"):
        normalize_phone("1" * 25)


def test_normalize_phone_boundary_8_digits_accepted():
    assert normalize_phone("12345678") == "12345678"


def test_normalize_phone_boundary_20_digits_accepted():
    twenty = "1" * 20
    assert normalize_phone(twenty) == twenty


def test_normalize_phone_logs_at_debug_when_input_changed(monkeypatch):
    # Patch the module-level logger directly so the test doesn't depend on
    # pytest caplog, the root logger's effective level, or fileConfig's
    # disable_existing_loggers (alembic.ini sets that, and earlier tests
    # in the suite that exercise migrations end up clobbering the
    # `app.notifications` logger).
    from app import notifications as notifications_module

    debug_calls: list[tuple[str, tuple, dict]] = []
    monkeypatch.setattr(
        notifications_module.log,
        "debug",
        lambda *args, **kwargs: debug_calls.append((args[0], args[1:], kwargs)),
    )
    normalize_phone("+212 6 11 20 45 02")
    rendered = [fmt % args for fmt, args, _kwargs in debug_calls]
    assert any(
        "phone_normalized" in line and "changed=True" in line for line in rendered
    ), f"no matching log call; saw {rendered}"


def test_normalize_phone_no_log_when_input_unchanged(monkeypatch):
    from app import notifications as notifications_module

    debug_calls: list[str] = []
    monkeypatch.setattr(
        notifications_module.log,
        "debug",
        lambda fmt, *args, **kwargs: debug_calls.append(fmt % args),
    )
    normalize_phone("212611204502")
    assert not any("phone_normalized" in line for line in debug_calls)


def test_back_compat_alias_still_works():
    # `_normalize_phone_number` is the historical private name; existing callers
    # in app/notifications.py still import it.
    assert _normalize_phone_number is normalize_phone
    assert _normalize_phone_number("06 11 20 45 02") == "0611204502"
