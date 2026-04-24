"""Persistent booking domain models for the v0.3 admin/CRM layer.

This module starts with framework-light models and pure helpers so the booking
lifecycle/reminder rules are testable before wiring SQLAlchemy sessions and the
admin UI around them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

BOOKING_STATUSES = (
    "draft",
    "awaiting_confirmation",
    "confirmed",
    "rescheduled",
    "customer_cancelled",
    "admin_cancelled",
    "expired",
    "no_show",
    "technician_en_route",
    "arrived",
    "in_progress",
    "completed",
    "completed_with_issue",
    "refunded",
)

FINAL_BOOKING_STATUSES = (
    "customer_cancelled",
    "admin_cancelled",
    "expired",
    "no_show",
    "completed",
    "completed_with_issue",
    "refunded",
)

# Guardrails for the operational workflow. This intentionally allows some admin
# recovery transitions (e.g. rescheduled -> confirmed) while preventing nonsense
# like completed -> in_progress.
_ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"awaiting_confirmation", "expired", "customer_cancelled", "admin_cancelled"},
    "awaiting_confirmation": {"confirmed", "expired", "customer_cancelled", "admin_cancelled"},
    "confirmed": {
        "rescheduled",
        "customer_cancelled",
        "admin_cancelled",
        "no_show",
        "technician_en_route",
        "arrived",
        "in_progress",
        "completed",
        "completed_with_issue",
    },
    "rescheduled": {"confirmed", "customer_cancelled", "admin_cancelled", "expired"},
    "technician_en_route": {"arrived", "in_progress", "completed", "no_show", "admin_cancelled"},
    "arrived": {"in_progress", "completed", "completed_with_issue", "no_show"},
    "in_progress": {"completed", "completed_with_issue"},
    "completed": {"completed_with_issue", "refunded"},
    "completed_with_issue": {"refunded"},
    "customer_cancelled": set(),
    "admin_cancelled": set(),
    "expired": set(),
    "no_show": set(),
    "refunded": set(),
}

REMINDER_ELIGIBLE_STATUSES = ("confirmed", "rescheduled")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def require_valid_status(status: str) -> None:
    if status not in BOOKING_STATUSES:
        raise ValueError(f"Unknown booking status: {status}")


@dataclass
class BookingStatusEvent:
    from_status: str
    to_status: str
    actor: str
    note: str = ""
    created_at: datetime = field(default_factory=utcnow)
    booking_id: int | None = None


@dataclass
class BookingRecord:
    phone: str
    status: str = "draft"
    id: int | None = None
    ref: str = ""
    customer_name: str = ""
    customer_vehicle_id: int | None = None
    vehicle_label: str = ""
    service_id: str = ""
    service_label: str = ""
    price_dh: int = 0
    promo_code: str = ""
    location_mode: str = ""
    appointment_start_at: datetime | None = None
    appointment_end_at: datetime | None = None
    timezone_name: str = "Africa/Casablanca"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    status_events: list[BookingStatusEvent] = field(default_factory=list)
    reminders: list["BookingReminder"] = field(default_factory=list)

    def __post_init__(self) -> None:
        require_valid_status(self.status)


@dataclass
class ReminderRule:
    name: str
    offset_minutes_before: int
    id: int | None = None
    enabled: bool = True
    max_sends: int = 1
    min_minutes_between_sends: int = 0
    template_name: str = ""
    channel: str = "whatsapp_template"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if self.offset_minutes_before <= 0:
            raise ValueError("offset_minutes_before must be positive")
        if self.max_sends < 1:
            raise ValueError("max_sends must be >= 1")
        if self.min_minutes_between_sends < 0:
            raise ValueError("min_minutes_between_sends must be >= 0")


@dataclass
class BookingReminder:
    booking_id: int | None
    rule_id: int | None
    kind: str
    scheduled_for: datetime
    status: str = "pending"
    sent_at: datetime | None = None
    attempt_count: int = 0
    error: str = ""
    created_at: datetime = field(default_factory=utcnow)


def transition_booking_status(
    booking: BookingRecord,
    new_status: str,
    *,
    actor: str,
    note: str = "",
    now: datetime | None = None,
) -> BookingStatusEvent:
    """Move a booking through a guarded lifecycle and append an audit event."""
    require_valid_status(new_status)
    if not actor:
        raise ValueError("actor is required")

    current = booking.status
    if current == new_status:
        raise ValueError(f"Booking is already {new_status}")

    allowed = _ALLOWED_STATUS_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise ValueError(f"Invalid booking status transition: {current} -> {new_status}")

    event = BookingStatusEvent(
        booking_id=booking.id,
        from_status=current,
        to_status=new_status,
        actor=actor,
        note=note,
        created_at=now or utcnow(),
    )
    booking.status = new_status
    booking.updated_at = event.created_at
    booking.status_events.append(event)

    if new_status in FINAL_BOOKING_STATUSES:
        cancel_pending_reminders(booking, reason=f"booking_status:{new_status}")

    return event


def cancel_pending_reminders(booking: BookingRecord, *, reason: str) -> int:
    """Cancel pending reminders when the booking can no longer receive them."""
    count = 0
    for reminder in booking.reminders:
        if reminder.status == "pending":
            reminder.status = "cancelled"
            reminder.error = reason
            count += 1
    return count


def create_reminders_for_booking(
    booking: BookingRecord,
    rules: Iterable[ReminderRule],
    *,
    now: datetime | None = None,
) -> list[BookingReminder]:
    """Generate concrete reminder rows from active rules for a confirmed booking.

    Rules are applied only to confirmed/rescheduled bookings with a precise
    appointment start datetime. Reminder times already in the past are skipped.
    """
    if booking.status not in REMINDER_ELIGIBLE_STATUSES:
        return []
    if booking.appointment_start_at is None:
        return []

    baseline = now or utcnow()
    existing_rule_ids = {r.rule_id for r in booking.reminders if r.rule_id is not None}
    generated: list[BookingReminder] = []

    for rule in rules:
        if not rule.enabled:
            continue
        if rule.id is not None and rule.id in existing_rule_ids:
            continue
        scheduled_for = booking.appointment_start_at - timedelta_minutes(rule.offset_minutes_before)
        if scheduled_for <= baseline:
            continue
        reminder = BookingReminder(
            booking_id=booking.id,
            rule_id=rule.id,
            kind=rule.name,
            scheduled_for=scheduled_for,
        )
        booking.reminders.append(reminder)
        generated.append(reminder)

    return generated


def timedelta_minutes(minutes: int):
    # Local wrapper keeps imports explicit near pure scheduling logic and makes
    # future timezone-aware changes easier to isolate.
    from datetime import timedelta

    return timedelta(minutes=minutes)
