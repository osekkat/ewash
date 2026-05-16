"""Internal WhatsApp notifications for operational staff."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import re
import time

from sqlalchemy import Engine

from . import meta
from .booking import Booking
from .config import settings
from .db import init_db, make_engine, session_scope
from .models import BookingNotificationSettingRow

log = logging.getLogger(__name__)

BOOKING_CONFIRMATION_SETTINGS_KEY = "booking_confirmation"


@dataclass(frozen=True)
class BookingNotificationSettings:
    enabled: bool = False
    phone_number: str = ""
    template_name: str = ""
    template_language: str = "fr"


@lru_cache(maxsize=1)
def _notification_engine() -> Engine | None:
    if not settings.database_url:
        return None
    engine = make_engine(settings.database_url)
    init_db(engine)
    return engine


def notification_cache_clear() -> None:
    _notification_engine.cache_clear()


def _engine_or_configured(engine: Engine | None = None) -> Engine | None:
    return engine if engine is not None else _notification_engine()


class InvalidPhone(ValueError):
    """Raised by :func:`normalize_phone` when the input can't be parsed as a
    valid phone number.

    Carries a stable ``error_code`` attribute so the API layer can map this
    exception to a 400 response with a machine-readable code without
    re-introspecting the message string. The API exception map in
    ``app/api.py`` should include::

        (notifications.InvalidPhone, 400, "invalid_phone")
    """

    error_code = "invalid_phone"


def normalize_phone(phone_number: str | None) -> str:
    """Normalize a free-text phone number to digits-only (8-20 chars).

    Strips spaces, plus signs, dashes, parentheses, and any other non-digit
    characters. Raises :class:`InvalidPhone` when the cleaned result is empty,
    1-7 digits, or 21+ digits.

    Moroccan local-format inputs are promoted to the 212-prefixed canonical:
      * 10 digits starting with ``0`` (``0611204502``) → ``212611204502``
      * 9 digits with no leading 0 (``611204502``) → ``212611204502``
        — this is what the PWA submits, since its recap UI shows ``+212`` as
        a visual prefix and the user only types the local part.

    Inputs that already begin with ``212`` or carry a different country code
    pass through unchanged.

    Used by both the WhatsApp path (via :func:`upsert_booking_notification_settings`)
    and the PWA path (`POST /api/v1/bookings`) so the same customer reaching
    Ewash through either channel dedupes to the same `customers.phone` row.
    """
    raw = phone_number or ""
    digits = re.sub(r"\D+", "", raw)
    if len(digits) == 10 and digits.startswith("0"):
        digits = "212" + digits[1:]
    elif len(digits) == 9:
        digits = "212" + digits
    if not (8 <= len(digits) <= 20):
        raise InvalidPhone(
            f"phone={raw!r} normalized to {digits!r} of length {len(digits)}, "
            f"must be 8-20 digits"
        )
    if digits != raw:
        log.debug("phone_normalized in=%r out=%r changed=True", raw, digits)
    return digits


# Back-compat alias: existing call sites import `_normalize_phone_number`.
# The leading underscore is preserved so nothing breaks; new callers should
# prefer the public name.
_normalize_phone_number = normalize_phone


def _normalize_template_name(template_name: str) -> str:
    cleaned = (template_name or "").strip()
    if not cleaned:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_]{2,160}", cleaned):
        raise ValueError("Template name must be 2-160 letters, numbers, or underscores")
    return cleaned


def _normalize_template_language(template_language: str) -> str:
    cleaned = (template_language or "fr").strip() or "fr"
    if not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", cleaned):
        raise ValueError("Template language must look like fr, en, or fr_FR")
    return cleaned


def get_booking_notification_settings(*, engine: Engine | None = None) -> BookingNotificationSettings:
    db_engine = _engine_or_configured(engine)
    if db_engine is None:
        return BookingNotificationSettings()
    try:
        with session_scope(db_engine) as session:
            row = session.get(BookingNotificationSettingRow, BOOKING_CONFIRMATION_SETTINGS_KEY)
            if row is None:
                return BookingNotificationSettings()
            return BookingNotificationSettings(
                enabled=row.enabled,
                phone_number=row.phone_number,
                template_name=row.template_name,
                template_language=row.template_language or "fr",
            )
    except Exception:
        log.exception("get_booking_notification_settings failed")
        return BookingNotificationSettings()


def upsert_booking_notification_settings(
    *,
    enabled: bool,
    phone_number: str,
    template_name: str,
    template_language: str = "fr",
    engine: Engine | None = None,
) -> BookingNotificationSettings:
    # Admins may persist a disabled config with no phone yet, so only run
    # the strict normalize_phone path when the field is non-empty. The if-empty
    # check below still rejects "enabled with no phone" the same as before.
    raw_phone = (phone_number or "").strip()
    normalized_phone = normalize_phone(raw_phone) if raw_phone else ""
    normalized_template = _normalize_template_name(template_name)
    normalized_language = _normalize_template_language(template_language)
    if enabled and (not normalized_phone or not normalized_template):
        raise ValueError("Phone number and template are required when notifications are enabled")

    db_engine = _engine_or_configured(engine)
    if db_engine is None:
        raise RuntimeError("DATABASE_URL is not configured")
    with session_scope(db_engine) as session:
        row = session.get(BookingNotificationSettingRow, BOOKING_CONFIRMATION_SETTINGS_KEY)
        if row is None:
            row = BookingNotificationSettingRow(settings_key=BOOKING_CONFIRMATION_SETTINGS_KEY)
            session.add(row)
        row.enabled = enabled
        row.phone_number = normalized_phone
        row.template_name = normalized_template
        row.template_language = normalized_language
    notification_cache_clear()
    return BookingNotificationSettings(
        enabled=enabled,
        phone_number=normalized_phone,
        template_name=normalized_template,
        template_language=normalized_language,
    )


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()) or "-"


def _vehicle_label(booking: Booking) -> str:
    vehicle = _clean(booking.vehicle_type)
    details = " ".join(part for part in (booking.car_model, booking.color) if part)
    if details:
        return _clean(f"{vehicle} - {details}")
    return vehicle


def _service_label(booking: Booking) -> str:
    parts = [_clean(booking.service_label or booking.service)]
    if booking.addon_service_label:
        parts.append(f"Esthetique: {_clean(booking.addon_service_label)}")
    return " + ".join(parts)


def _location_label(booking: Booking) -> str:
    if booking.location_mode == "center":
        return _clean(booking.center or booking.location_name or "Stand Ewash")
    if booking.address:
        return _clean(booking.address)
    if booking.location_address:
        return _clean(booking.location_address)
    if booking.geo:
        return _clean(booking.geo)
    return "-"


def booking_notification_parameters(
    booking: Booking,
    *,
    event_label: str = "Nouvelle reservation",
) -> list[str]:
    total = (booking.price_dh or 0) + (booking.addon_price_dh or 0)
    date_slot = " - ".join(part for part in (booking.date_label, booking.slot) if part)
    return [
        _clean(event_label),
        _clean(booking.ref),
        _clean(booking.name),
        _clean(f"+{booking.phone}" if booking.phone else ""),
        _vehicle_label(booking),
        _service_label(booking),
        _clean(date_slot),
        _location_label(booking),
        f"{total} DH" if total else "-",
        _clean(booking.note),
    ]


async def notify_booking_confirmation(
    booking: Booking,
    *,
    event_label: str = "Nouvelle reservation",
) -> bool:
    config = get_booking_notification_settings()
    if not config.enabled or not config.phone_number or not config.template_name:
        return False
    try:
        await meta.send_template(
            config.phone_number,
            config.template_name,
            language_code="fr",
            body_parameters=booking_notification_parameters(booking, event_label=event_label),
        )
    except meta.MetaSendError as exc:
        log.exception(
            "booking notification failed ref=%s to=%s status=%s path=%s body=%s",
            booking.ref,
            config.phone_number,
            exc.status_code,
            exc.request_path,
            exc.body,
        )
        return False
    except Exception:
        log.exception("booking notification failed ref=%s to=%s", booking.ref, config.phone_number)
        return False
    return True


async def notify_booking_confirmation_safe(
    booking: Booking,
    *,
    event_label: str = "Nouvelle reservation",
) -> None:
    """BackgroundTask wrapper that logs failures without surfacing them to customers."""
    started = time.perf_counter()
    try:
        result = await notify_booking_confirmation(booking, event_label=event_label)
        duration_ms = (time.perf_counter() - started) * 1000
        log_method = log.info if result else log.error
        status = "sent" if result else "failed"
        log_method(
            "notifications.staff_alert %s ref=%s event=%s duration_ms=%.1f result=%s",
            status,
            booking.ref,
            event_label,
            duration_ms,
            result,
        )
    except Exception:
        duration_ms = (time.perf_counter() - started) * 1000
        log.exception(
            "notifications.staff_alert failed ref=%s event=%s duration_ms=%.1f result=exception",
            booking.ref,
            event_label,
            duration_ms,
        )
