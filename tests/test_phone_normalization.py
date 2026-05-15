"""Tests for app.notifications.normalize_phone — used by WhatsApp + PWA paths."""
from __future__ import annotations

import logging

import pytest

from app.notifications import InvalidPhone, _normalize_phone_number, normalize_phone


def test_normalize_phone_identity_when_already_canonical():
    # 212-prefixed input is already canonical and passes through unchanged.
    assert normalize_phone("212611204502") == "212611204502"


def test_normalize_phone_strips_internal_whitespace():
    # Whitespace strip composes with the canonical-passthrough path.
    assert normalize_phone("212 611 204 502") == "212611204502"


def test_normalize_phone_strips_plus_and_whitespace():
    assert normalize_phone("+212 6 11 20 45 02") == "212611204502"


def test_normalize_phone_moroccan_local_with_leading_zero():
    # 10-digit Moroccan local format (0XXXXXXXXX) → drop the leading 0 and
    # prepend 212. Matches the dedup invariant in ewash-6pa.8.13:
    # "+212 6 11 20 45 02" and "212611204502" must hit one customers row.
    assert normalize_phone("0611204502") == "212611204502"
    assert normalize_phone("06 11 20 45 02") == "212611204502"


def test_normalize_phone_moroccan_local_no_leading_zero():
    # 9-digit local format (no leading 0) → prepend 212. This is what the
    # PWA submits because mobile-app/booking.jsx renders "+212" as a visual
    # prefix and only sends the user-typed local digits in the payload.
    assert normalize_phone("611204502") == "212611204502"
    assert normalize_phone("665883062") == "212665883062"


def test_normalize_phone_strips_dashes_and_parens():
    assert normalize_phone("+1 (212) 555-1234") == "12125551234"


def test_normalize_phone_empty_input_raises_invalid_phone():
    # Strict contract: empty input is not a valid phone — raise so callers
    # can't silently persist a blank row.
    with pytest.raises(InvalidPhone):
        normalize_phone("")
    with pytest.raises(InvalidPhone):
        normalize_phone(None)


def test_normalize_phone_too_short_raises_invalid_phone():
    with pytest.raises(InvalidPhone, match="8-20 digits"):
        normalize_phone("123")


def test_normalize_phone_too_long_raises_invalid_phone():
    with pytest.raises(InvalidPhone, match="8-20 digits"):
        normalize_phone("1" * 25)


def test_invalid_phone_has_stable_error_code():
    # The API layer matches on this attribute, not the message string.
    assert InvalidPhone.error_code == "invalid_phone"
    try:
        normalize_phone("123")
    except InvalidPhone as exc:
        assert exc.error_code == "invalid_phone"
    else:
        pytest.fail("expected InvalidPhone")


def test_invalid_phone_is_value_error_subclass():
    # Callers that catch ValueError keep working (back-compat with old contract).
    assert issubclass(InvalidPhone, ValueError)


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
    assert _normalize_phone_number("06 11 20 45 02") == "212611204502"
