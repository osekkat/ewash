"""Unit tests for ``app.api_schemas`` — the Pydantic contract layer for
``/api/v1/*``. The schemas enforce ``extra="forbid"`` so PWA typos like
``addons`` (vs ``addon_ids``) surface as 422 at the contract boundary instead
of being silently dropped on the floor."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api_schemas import (
    BookingCreateRequest,
    PromoValidateRequest,
)


def _base_payload(**overrides) -> dict:
    """Return a valid kwargs dict for ``BookingCreateRequest``.

    Each test overrides exactly one field to assert that field's behaviour
    without entangling itself with the other field rules."""
    payload = {
        "phone": "212611204502",
        "name": "Test Client",
        "category": "A",
        "location": {"kind": "home", "pin_address": "33.5,-7.6"},
        "service_id": "svc_cpl",
        "date": "2026-06-15",
        "slot": "slot_9_11",
    }
    payload.update(overrides)
    return payload


def test_booking_create_request_strict_rejects_unknown():
    # "addons" instead of "addon_ids" → ValidationError.
    with pytest.raises(ValidationError) as exc:
        BookingCreateRequest(**_base_payload(addons=["x"]))
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_booking_create_request_strips_whitespace():
    req = BookingCreateRequest(**_base_payload(phone="  212611204502  "))
    assert req.phone == "212611204502"


def test_category_case_insensitive():
    req = BookingCreateRequest(**_base_payload(category="a"))
    assert req.category == "A"


def test_date_format_pattern():
    with pytest.raises(ValidationError):
        BookingCreateRequest(**_base_payload(date="2026/05/20"))


def test_date_must_be_valid_calendar_date():
    # The regex would pass "2026-02-30" but the after-validator catches it.
    with pytest.raises(ValidationError):
        BookingCreateRequest(**_base_payload(date="2026-02-30"))


def test_addon_ids_max_10():
    with pytest.raises(ValidationError):
        BookingCreateRequest(**_base_payload(addon_ids=["x"] * 11))


def test_oversize_note():
    with pytest.raises(ValidationError):
        BookingCreateRequest(**_base_payload(note="a" * 501))


def test_client_request_id_pattern():
    with pytest.raises(ValidationError):
        BookingCreateRequest(**_base_payload(client_request_id="!@#"))


def test_promo_validate_request_strict():
    with pytest.raises(ValidationError) as exc:
        PromoValidateRequest(code="X", category="A", extra_field="x")
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())
