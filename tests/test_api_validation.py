"""Tests for app.api_validation — the server-side contract validators.

Each test uses a pinned `now` to keep the +2h freshness check deterministic.
The default closed-date set comes from the static catalog (2026-05-27 and
2026-05-28 — Eid al-Adha). The default active slots come from `SLOTS` in
`app/catalog.py`. No database fixture is required: when no engine is configured
the catalog helpers fall back to the static data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.api_validation import (
    APIValidationError,
    CASABLANCA_TZ,
    CenterIdNotAllowed,
    ClosedDate,
    DuplicateAddon,
    InvalidDate,
    InvalidServiceForCategory,
    MissingCenterId,
    NotADetailingService,
    SlotTooSoon,
    UnknownAddon,
    UnknownCenter,
    UnknownService,
    UnknownSlot,
    validate_addon_ids,
    validate_center_id,
    validate_service_for_category,
    validate_slot_and_date,
)


def test_closed_date_raises_closed_date() -> None:
    # 2026-05-27 is Eid al-Adha in CLOSED_DATES — must be rejected even though
    # the slot itself is valid and the time is far enough in the future.
    with pytest.raises(ClosedDate) as exc_info:
        validate_slot_and_date(
            "2026-05-27",
            "slot_9_11",
            now=datetime(2026, 5, 20, 9, 0, tzinfo=CASABLANCA_TZ),
        )
    assert exc_info.value.error_code == "closed_date"


def test_unknown_slot_raises_unknown_slot() -> None:
    with pytest.raises(UnknownSlot) as exc_info:
        validate_slot_and_date(
            "2026-06-15",
            "slot_99_99",
            now=datetime(2026, 6, 14, 9, 0, tzinfo=CASABLANCA_TZ),
        )
    assert exc_info.value.error_code == "unknown_slot"


def test_slot_30_minutes_in_future_raises_too_soon() -> None:
    # slot_9_11 starts at 09:00 Casablanca. With now=08:30 the lead is 30 min.
    with pytest.raises(SlotTooSoon) as exc_info:
        validate_slot_and_date(
            "2026-06-15",
            "slot_9_11",
            now=datetime(2026, 6, 15, 8, 30, tzinfo=CASABLANCA_TZ),
        )
    assert exc_info.value.error_code == "slot_too_soon"


def test_slot_2h_1min_in_future_passes() -> None:
    # slot_11_13 starts at 11:00 Casablanca. With now=08:59 the lead is 2h 1min.
    # No exception should be raised.
    validate_slot_and_date(
        "2026-06-15",
        "slot_11_13",
        now=datetime(2026, 6, 15, 8, 59, tzinfo=CASABLANCA_TZ),
    )


def test_slot_5h_in_future_passes() -> None:
    # slot_14_16 starts at 14:00 Casablanca. With now=09:00 the lead is 5h.
    validate_slot_and_date(
        "2026-06-15",
        "slot_14_16",
        now=datetime(2026, 6, 15, 9, 0, tzinfo=CASABLANCA_TZ),
    )


def test_bad_date_format_raises_invalid_date() -> None:
    with pytest.raises(InvalidDate) as exc_info:
        validate_slot_and_date(
            "2026/06/15",
            "slot_9_11",
            now=datetime(2026, 6, 14, 9, 0, tzinfo=CASABLANCA_TZ),
        )
    assert exc_info.value.error_code == "invalid_date"


def test_utc_now_converted_to_casablanca_tz() -> None:
    # 06:00 UTC is 07:00 Casablanca (UTC+1, no DST mid-summer). With slot_18_20
    # on 2026-07-15 that's an 11-hour lead — well above the 2h threshold. The
    # test asserts the function accepts a UTC `now` and converts it, instead of
    # crashing on a non-Casablanca tz input.
    validate_slot_and_date(
        "2026-07-15",
        "slot_18_20",
        now=datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc),
    )

    # Boundary check the other way: 09:00 UTC = 10:00 Casablanca. slot_11_13
    # starts at 11:00 Casablanca, lead = 1h → too soon. Confirms the tz math
    # is applied before the freshness comparison.
    with pytest.raises(SlotTooSoon):
        validate_slot_and_date(
            "2026-07-15",
            "slot_11_13",
            now=datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc),
        )


def test_exceptions_are_value_error_subclasses() -> None:
    # Epic 6pa.3 acceptance criterion: validators raise ValueError with a
    # stable `error_code` attribute. APIValidationError subclasses ValueError,
    # and each concrete error class sets `error_code` at the class level so
    # the API layer can read it without instantiating.
    assert issubclass(APIValidationError, ValueError)
    for cls, code in (
        (ClosedDate, "closed_date"),
        (UnknownSlot, "unknown_slot"),
        (SlotTooSoon, "slot_too_soon"),
        (InvalidDate, "invalid_date"),
    ):
        assert issubclass(cls, APIValidationError)
        assert cls.error_code == code


def test_naive_now_rejected() -> None:
    # Defensive: a naive `now` would silently use local-tz semantics inside
    # `.astimezone()`, which is platform-dependent and flaky. Document that
    # callers must pass tz-aware datetimes.
    with pytest.raises((TypeError, ValueError)):
        validate_slot_and_date(
            "2026-06-15",
            "slot_9_11",
            now=datetime(2026, 6, 15, 8, 30),
        )


def test_static_closed_dates_uses_eid_2026_day_2() -> None:
    # Belt-and-suspenders: confirm CLOSED_DATES includes the second Eid day too,
    # so a bug that only checks the first day would still be caught.
    with pytest.raises(ClosedDate):
        validate_slot_and_date(
            "2026-05-28",
            "slot_9_11",
            now=datetime(2026, 5, 20, 9, 0, tzinfo=CASABLANCA_TZ),
        )


def test_exact_2h_boundary_passes() -> None:
    # slot_9_11 starts at 09:00 Casablanca. With now=07:00 the lead is exactly
    # 2h. The check is `candidate < now + 2h`, so exactly 2h is OK.
    validate_slot_and_date(
        "2026-06-15",
        "slot_9_11",
        now=datetime(2026, 6, 15, 7, 0, tzinfo=CASABLANCA_TZ),
    )


def test_double_digit_slot_id_parses() -> None:
    # slot_20_22 has double-digit hours on both sides. now=10:00 → lead=10h → ok.
    validate_slot_and_date(
        "2026-06-15",
        "slot_20_22",
        now=datetime(2026, 6, 15, 10, 0, tzinfo=CASABLANCA_TZ),
    )


def test_passing_now_in_arbitrary_tz_works() -> None:
    # Tokyo is UTC+9; 2026-07-15 17:00 Tokyo = 09:00 Casablanca.
    # slot_14_16 starts at 14:00 Casablanca → lead=5h → ok.
    tokyo = ZoneInfo("Asia/Tokyo")
    validate_slot_and_date(
        "2026-07-15",
        "slot_14_16",
        now=datetime(2026, 7, 15, 17, 0, tzinfo=tokyo),
    )


# ─────────────────────────────────────────────────────────────────────────────
# validate_service_for_category
# ─────────────────────────────────────────────────────────────────────────────


def test_validate_service_for_category_car_service_with_car_category() -> None:
    # svc_cpl is a car wash service; category B is a car category.
    validate_service_for_category("svc_cpl", "B")


def test_validate_service_for_category_moto_service_with_moto_category() -> None:
    validate_service_for_category("svc_moto", "MOTO")
    validate_service_for_category("svc_scooter", "MOTO")


def test_validate_service_for_category_moto_service_with_car_rejected() -> None:
    with pytest.raises(InvalidServiceForCategory) as exc_info:
        validate_service_for_category("svc_moto", "A")
    assert exc_info.value.error_code == "service_category_mismatch"


def test_validate_service_for_category_car_service_with_moto_rejected() -> None:
    # svc_cpl is car-only; pairing with MOTO must raise.
    with pytest.raises(InvalidServiceForCategory) as exc_info:
        validate_service_for_category("svc_cpl", "MOTO")
    assert exc_info.value.error_code == "service_category_mismatch"


def test_validate_service_for_category_unknown_service_raises() -> None:
    with pytest.raises(UnknownService) as exc_info:
        validate_service_for_category("svc_does_not_exist", "A")
    assert exc_info.value.error_code == "unknown_service"


def test_validate_service_for_category_all_car_categories_accepted() -> None:
    # Every car category (A/B/C) should pair cleanly with a car detailing service.
    for category in ("A", "B", "C"):
        validate_service_for_category("svc_pol", category)


def test_validate_service_for_category_logs_rejection(caplog) -> None:
    # Staff might want to grep "validation.rejection" to spot stale PWA clients
    # hammering invalid combos. Confirm the INFO line is emitted.
    import logging

    caplog.set_level(logging.INFO, logger="app.api_validation")
    with pytest.raises(InvalidServiceForCategory):
        validate_service_for_category("svc_cpl", "MOTO")
    assert any("validation.rejection" in rec.message for rec in caplog.records)


def test_service_validation_exceptions_are_api_validation_errors() -> None:
    # Same hierarchy contract as the slot/date validators.
    assert issubclass(UnknownService, APIValidationError)
    assert issubclass(InvalidServiceForCategory, APIValidationError)
    assert UnknownService.error_code == "unknown_service"
    assert InvalidServiceForCategory.error_code == "service_category_mismatch"


def test_validate_addon_ids_empty_list_returns_empty() -> None:
    # Customer skipped the upsell. Empty input is the common case, must pass.
    assert validate_addon_ids([]) == []


def test_validate_addon_ids_returns_same_list_for_all_valid_detailing() -> None:
    # Two real detailing services from SERVICES_DETAILING — should round-trip.
    addons = ["svc_cuir", "svc_plastq"]
    assert validate_addon_ids(addons) == addons


def test_validate_addon_ids_rejects_unknown_id() -> None:
    with pytest.raises(UnknownAddon) as exc_info:
        validate_addon_ids(["svc_does_not_exist"])
    assert exc_info.value.error_code == "unknown_addon"


def test_validate_addon_ids_rejects_wash_service() -> None:
    # svc_cpl is wash-bucket — has its own pricing per category, must not
    # be used as a free-form addon.
    with pytest.raises(NotADetailingService) as exc_info:
        validate_addon_ids(["svc_cpl"])
    assert exc_info.value.error_code == "not_a_detailing_service"
    assert "bucket=wash" in str(exc_info.value)


def test_validate_addon_ids_rejects_moto_service() -> None:
    # svc_moto is in SERVICES_MOTO — also not a detailing service.
    with pytest.raises(NotADetailingService) as exc_info:
        validate_addon_ids(["svc_moto"])
    assert exc_info.value.error_code == "not_a_detailing_service"
    assert "bucket=moto" in str(exc_info.value)


def test_validate_addon_ids_rejects_duplicates() -> None:
    # Two BookingLineItemRow rows with the same service_id would be confusing
    # admin-side and add no value to the customer's upsell list.
    with pytest.raises(DuplicateAddon) as exc_info:
        validate_addon_ids(["svc_cuir", "svc_cuir"])
    assert exc_info.value.error_code == "duplicate_addon"


def test_validate_addon_ids_logs_rejection(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="app.api_validation")
    with pytest.raises(UnknownAddon):
        validate_addon_ids(["svc_unknown"])
    assert any(
        "validation.rejection" in rec.message and "addon_id=svc_unknown" in rec.message
        for rec in caplog.records
    )


def test_validate_addon_ids_exceptions_are_api_validation_errors() -> None:
    # Stable error_code contract for all three addon-validation exceptions.
    assert issubclass(UnknownAddon, APIValidationError)
    assert issubclass(DuplicateAddon, APIValidationError)
    assert issubclass(NotADetailingService, APIValidationError)
    assert UnknownAddon.error_code == "unknown_addon"
    assert DuplicateAddon.error_code == "duplicate_addon"
    assert NotADetailingService.error_code == "not_a_detailing_service"


def test_validate_center_id_home_with_no_center_passes() -> None:
    # Home delivery: center_id absent is the happy path.
    validate_center_id(None, location_kind="home")


def test_validate_center_id_home_with_center_rejected() -> None:
    # Home delivery shouldn't carry a center_id; widening the contract here
    # would let a tampered PWA confuse the staff alert.
    with pytest.raises(CenterIdNotAllowed) as exc_info:
        validate_center_id("ctr_casa", location_kind="home")
    assert exc_info.value.error_code == "center_id_not_allowed"


def test_validate_center_id_center_missing_rejected() -> None:
    # location.kind=center must come with a center_id; empty/None is rejected.
    with pytest.raises(MissingCenterId) as exc_info:
        validate_center_id(None, location_kind="center")
    assert exc_info.value.error_code == "missing_center_id"


def test_validate_center_id_center_with_unknown_rejected() -> None:
    # center_id must match one of catalog.active_centers().
    with pytest.raises(UnknownCenter) as exc_info:
        validate_center_id("ctr_nope", location_kind="center")
    assert exc_info.value.error_code == "unknown_center"


def test_validate_center_id_center_with_valid_static_id_passes() -> None:
    # The static catalog ships a single active center, "ctr_casa".
    validate_center_id("ctr_casa", location_kind="center")


def test_validate_center_id_empty_string_with_center_kind_rejected() -> None:
    # Empty string is not "missing" in Python's truthy sense — assert we treat
    # it the same as None so the JSON contract is consistent.
    with pytest.raises(MissingCenterId):
        validate_center_id("", location_kind="center")


def test_validate_center_id_exceptions_are_api_validation_errors() -> None:
    # Stable error_code contract.
    assert issubclass(CenterIdNotAllowed, APIValidationError)
    assert issubclass(MissingCenterId, APIValidationError)
    assert issubclass(UnknownCenter, APIValidationError)
    assert CenterIdNotAllowed.error_code == "center_id_not_allowed"
    assert MissingCenterId.error_code == "missing_center_id"
    assert UnknownCenter.error_code == "unknown_center"
