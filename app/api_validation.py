"""Domain validators for the planned /api/v1/* router.

Server-side source of truth for the contract between the PWA and the backend.
Anything the PWA enforces in the browser must be re-enforced here because a
tampered client could bypass it. The 2-hour slot-freshness rule and the closed-
date list both live here, in Africa/Casablanca time.

Each validator raises an `APIValidationError` subclass with a stable
`error_code` attribute so the API layer can map exceptions → 400 responses
with a machine-readable code without re-introspecting the message string.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta
from typing import overload
from zoneinfo import ZoneInfo

from sqlalchemy import Engine

from .catalog import (
    SERVICES_CAR,
    SERVICES_DETAILING,
    SERVICES_MOTO,
    active_closed_dates,
    active_time_slots,
)

log = logging.getLogger(__name__)

CASABLANCA_TZ = ZoneInfo("Africa/Casablanca")
MIN_LEAD_HOURS = 2
_SLOT_ID_PATTERN = re.compile(r"^slot_(\d+)_(\d+)$")
_HORIZONTAL_WHITESPACE_RUN = re.compile(r"[ \t]+")


class APIValidationError(ValueError):
    """Base for domain validation errors with stable error codes for API responses."""

    error_code: str = "validation_error"

    def __init__(self, message: str = "", *, error_code: str | None = None) -> None:
        super().__init__(message)
        if error_code:
            self.error_code = error_code


class ClosedDate(APIValidationError):
    error_code = "closed_date"


class UnknownSlot(APIValidationError):
    error_code = "unknown_slot"


class SlotTooSoon(APIValidationError):
    error_code = "slot_too_soon"


class InvalidDate(APIValidationError):
    error_code = "invalid_date"


class UnknownService(APIValidationError):
    error_code = "unknown_service"


class InvalidServiceForCategory(APIValidationError):
    error_code = "service_category_mismatch"


class UnknownAddon(APIValidationError):
    error_code = "unknown_addon"


class DuplicateAddon(APIValidationError):
    error_code = "duplicate_addon"


class NotADetailingService(APIValidationError):
    error_code = "not_a_detailing_service"


_CAR_SERVICE_IDS: frozenset[str] = frozenset(sid for sid, *_ in SERVICES_CAR)
_MOTO_SERVICE_IDS: frozenset[str] = frozenset(sid for sid, *_ in SERVICES_MOTO)
_DETAILING_SERVICE_IDS: frozenset[str] = frozenset(sid for sid, *_ in SERVICES_DETAILING)


def validate_service_for_category(service_id: str, category: str) -> None:
    """Raise if `service_id` belongs to the wrong vehicle lane for `category`.

    A moto service paired with a car category (or vice versa) is rejected
    before any DB write. The static catalog lists (`SERVICES_CAR`,
    `SERVICES_MOTO`) are the source of truth for lane membership; admin
    pricing overrides don't change which list a service lives in.

    Parameters
    ----------
    service_id : str
        Service id from the catalog (e.g., "svc_cpl", "svc_moto").
    category : str
        Vehicle category — "A" / "B" / "C" for cars, "MOTO" for two-wheels.

    Raises
    ------
    UnknownService : if `service_id` is not in either static list.
    InvalidServiceForCategory : if the lanes don't match.
    """
    if service_id in _CAR_SERVICE_IDS:
        service_lane = "car"
    elif service_id in _MOTO_SERVICE_IDS:
        service_lane = "moto"
    else:
        log.info(
            "validation.rejection service=%s category=%s reason=unknown_service",
            service_id,
            category,
        )
        raise UnknownService(f"service_id={service_id} not found")

    expected_lane = "moto" if category == "MOTO" else "car"
    if service_lane != expected_lane:
        log.info(
            "validation.rejection service=%s category=%s reason=service_category_mismatch",
            service_id,
            category,
        )
        raise InvalidServiceForCategory(
            f"service={service_id} requires lane={service_lane}, "
            f"but category={category} is lane={expected_lane}"
        )


def validate_slot_and_date(
    date_iso: str,
    slot_id: str,
    *,
    now: datetime | None = None,
    engine: Engine | None = None,
) -> None:
    """Reject closed dates, unknown slots, and slots <2h ahead in Africa/Casablanca.

    The 2-hour freshness rule is the server-side source of truth — the PWA's
    client-side `now+2h` filter is decorative and bypassable.

    Parameters
    ----------
    date_iso : str
        ISO date string (YYYY-MM-DD).
    slot_id : str
        Slot identifier from the catalog (e.g., "slot_9_11").
    now : datetime, optional
        For tests, pin the clock to a specific Africa/Casablanca instant.
        Must be tz-aware. Defaults to the wall-clock time.
    engine : Engine, optional
        Override the SQLAlchemy engine used to load closed dates / slots.

    Raises
    ------
    ClosedDate : if `date_iso` is in the active closed-date set.
    UnknownSlot : if `slot_id` is not an active slot.
    InvalidDate : if `date_iso` cannot be parsed as YYYY-MM-DD.
    SlotTooSoon : if the slot starts <2h after `now` (Africa/Casablanca).
    """
    if now is None:
        now_local = datetime.now(tz=CASABLANCA_TZ)
    else:
        now_local = now.astimezone(CASABLANCA_TZ)

    if date_iso in active_closed_dates(engine=engine):
        raise ClosedDate(f"date={date_iso} is in active_closed_dates")

    active_slot_ids = {entry[0] for entry in active_time_slots(engine=engine)}
    if slot_id not in active_slot_ids:
        raise UnknownSlot(f"slot_id={slot_id} not active")

    match = _SLOT_ID_PATTERN.match(slot_id)
    if match is None:
        raise UnknownSlot(f"slot_id={slot_id} doesn't match expected pattern")
    start_hour = int(match.group(1))

    try:
        appointment_date = datetime.strptime(date_iso, "%Y-%m-%d").date()
    except ValueError as exc:
        raise InvalidDate(f"date={date_iso} not parseable") from exc

    candidate = datetime(
        appointment_date.year,
        appointment_date.month,
        appointment_date.day,
        start_hour,
        0,
        tzinfo=CASABLANCA_TZ,
    )

    if candidate < now_local + timedelta(hours=MIN_LEAD_HOURS):
        log.info(
            "slot_too_soon: candidate=%s now=%s lead_hours=%d",
            candidate.isoformat(),
            now_local.isoformat(),
            MIN_LEAD_HOURS,
        )
        raise SlotTooSoon(
            f"slot={slot_id} on date={date_iso} starts {candidate.isoformat()}, "
            f"less than {MIN_LEAD_HOURS}h after now={now_local.isoformat()}"
        )


@overload
def clean_text(value: None, *, max_len: int) -> None: ...
@overload
def clean_text(value: str, *, max_len: int) -> str | None: ...


def clean_text(value: str | None, *, max_len: int) -> str | None:
    """Sanitize a free-text user input field defensively.

    Applies four passes, in order:

    1. Strip ASCII/Unicode control characters (Unicode category ``Cc``), with
       ``\\n`` deliberately preserved so multi-line customer notes survive
       ("Sonner deux fois\\nÉtage 3, porte gauche").
    2. Collapse runs of horizontal whitespace (spaces and tabs) into a single
       space. Newlines pass through untouched.
    3. Trim leading and trailing whitespace.
    4. Truncate the result to ``max_len`` characters.

    Returns ``None`` for ``None`` input, and also ``None`` if the cleaned
    string is empty (e.g., input was just whitespace or control characters).
    This contract lets callers distinguish "user explicitly typed something"
    from "user left the field blank" without juggling empty strings.

    The Pydantic schemas in :mod:`app.api_schemas` already enforce
    ``max_length`` at the request boundary; calling :func:`clean_text`
    afterwards is a belt-and-suspenders defense for downstream code paths
    (logging, persistence, staff alert text) where surprising control chars
    would otherwise leak through.
    """
    if value is None:
        return None
    no_controls = "".join(
        ch for ch in value if ch == "\n" or unicodedata.category(ch) != "Cc"
    )
    collapsed = _HORIZONTAL_WHITESPACE_RUN.sub(" ", no_controls)
    trimmed = collapsed.strip()
    if not trimmed:
        return None
    return trimmed[:max_len]


def validate_addon_ids(addon_ids: list[str]) -> list[str]:
    """Return ``addon_ids`` if every id is a known detailing-bucket service.

    Addons in the PWA booking flow are upsells from the ``ESTHÉTIQUE`` /
    detailing bucket (Polishing, Ceramic, Renovation, Lustre …). Wash-bucket
    or moto-bucket service ids are rejected — they belong in the main
    ``service_id`` field, not as addons.

    Parameters
    ----------
    addon_ids : list[str]
        Service ids from the catalog (e.g., ``["svc_cuir", "svc_plastq"]``).
        An empty list is valid (the customer didn't pick an upsell).

    Returns
    -------
    list[str]
        The same list, unchanged, when every id passes.

    Raises
    ------
    DuplicateAddon : if the same id is listed twice (two `BookingLineItemRow`
        rows with identical service_id would muddy the data; reject early).
    UnknownAddon : if an id is not in any static service catalog.
    NotADetailingService : if the id exists but lives in the wash or moto
        bucket — it cannot be used as an addon.
    """
    seen: set[str] = set()
    for addon_id in addon_ids:
        if addon_id in seen:
            log.info(
                "validation.rejection addon_id=%s reason=duplicate_addon",
                addon_id,
            )
            raise DuplicateAddon(f"addon_id={addon_id} listed twice")
        seen.add(addon_id)

        if addon_id in _DETAILING_SERVICE_IDS:
            continue
        if addon_id in _CAR_SERVICE_IDS or addon_id in _MOTO_SERVICE_IDS:
            bucket = "moto" if addon_id in _MOTO_SERVICE_IDS else "wash"
            log.info(
                "validation.rejection addon_id=%s bucket=%s reason=not_a_detailing_service",
                addon_id,
                bucket,
            )
            raise NotADetailingService(
                f"addon_id={addon_id} is in bucket={bucket}, addons must be detailing services"
            )
        log.info(
            "validation.rejection addon_id=%s reason=unknown_addon",
            addon_id,
        )
        raise UnknownAddon(f"addon_id={addon_id} not found")

    return addon_ids
