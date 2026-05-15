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
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Engine

from .catalog import active_closed_dates, active_time_slots

log = logging.getLogger(__name__)

CASABLANCA_TZ = ZoneInfo("Africa/Casablanca")
MIN_LEAD_HOURS = 2
_SLOT_ID_PATTERN = re.compile(r"^slot_(\d+)_(\d+)$")


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
