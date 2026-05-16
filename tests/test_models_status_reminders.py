from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    ALLOWED_STATUS_TRANSITIONS,
    BOOKING_STATUSES,
    FINAL_BOOKING_STATUSES,
    BookingRecord,
    BookingStatusEvent,
    ReminderRule,
    BookingReminder,
    create_reminders_for_booking,
    transition_booking_status,
)


def test_booking_statuses_cover_full_operational_lifecycle():
    assert BOOKING_STATUSES == (
        "draft",
        "awaiting_confirmation",
        "pending_ewash_confirmation",
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
    assert FINAL_BOOKING_STATUSES == (
        "customer_cancelled",
        "admin_cancelled",
        "expired",
        "no_show",
        "completed",
        "completed_with_issue",
        "refunded",
    )


def test_transition_booking_status_records_append_only_event():
    booking = BookingRecord(phone="212665883062", status="awaiting_confirmation")

    event = transition_booking_status(
        booking,
        "pending_ewash_confirmation",
        actor="customer",
        note="Confirmed from WhatsApp recap",
    )

    assert booking.status == "pending_ewash_confirmation"
    assert isinstance(event, BookingStatusEvent)
    assert event.from_status == "awaiting_confirmation"
    assert event.to_status == "pending_ewash_confirmation"
    assert event.actor == "customer"
    assert event.note == "Confirmed from WhatsApp recap"
    assert booking.status_events == [event]


def test_invalid_booking_status_transition_is_rejected():
    booking = BookingRecord(phone="212665883062", status="completed")

    with pytest.raises(ValueError):
        transition_booking_status(booking, "in_progress", actor="admin")


def test_draft_can_transition_directly_to_pending_ewash_confirmation():
    """ewash-osw: the live customer-confirm flow (WhatsApp BOOK_CONFIRM and the
    planned PWA POST /api/v1/bookings) goes from a brand-new ``draft`` to
    ``pending_ewash_confirmation`` in a single ``persist_confirmed_booking``
    transaction. The FSM must reflect that — otherwise the
    ``BookingStatusEventRow`` written by ``_persist_confirmed_booking_in_session``
    records a (from='draft', to='pending_ewash_confirmation') pair that the
    spec disallows, and any future caller routed through
    ``transition_booking_status`` would raise ``ValueError``.
    """
    booking = BookingRecord(phone="212665883062", status="draft")

    event = transition_booking_status(
        booking,
        "pending_ewash_confirmation",
        actor="customer",
        note="Confirmation WhatsApp",
    )

    assert booking.status == "pending_ewash_confirmation"
    assert event.from_status == "draft"
    assert event.to_status == "pending_ewash_confirmation"
    # The transition the live persist path records must be in the spec.
    assert "pending_ewash_confirmation" in ALLOWED_STATUS_TRANSITIONS["draft"]


def test_draft_to_awaiting_confirmation_path_still_works():
    """The legacy intermediate ``awaiting_confirmation`` bucket is still
    reachable from ``draft`` — kept so admin imports and reserved/future flows
    have a parking state that ``/admin`` already surfaces a count for. The
    ewash-osw fix added ``pending_ewash_confirmation`` as a *second* allowed
    target on the ``draft`` key without removing the older one.
    """
    booking = BookingRecord(phone="212665883062", status="draft")

    transition_booking_status(booking, "awaiting_confirmation", actor="admin")
    assert booking.status == "awaiting_confirmation"

    transition_booking_status(booking, "pending_ewash_confirmation", actor="customer")
    assert booking.status == "pending_ewash_confirmation"


def test_pending_booking_cannot_skip_ewash_confirmation_to_rescheduled():
    booking = BookingRecord(phone="212665883062", status="pending_ewash_confirmation")

    with pytest.raises(ValueError, match="pending_ewash_confirmation -> rescheduled"):
        transition_booking_status(booking, "rescheduled", actor="admin")

    assert booking.status == "pending_ewash_confirmation"
    assert booking.status_events == []


def test_reminders_are_generated_from_active_rules_for_confirmed_bookings_only():
    appointment = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    booking = BookingRecord(
        phone="212665883062",
        status="confirmed",
        appointment_start_at=appointment,
    )
    rules = [
        ReminderRule(name="J-1", offset_minutes_before=1440, template_name="booking_reminder_j1"),
        ReminderRule(name="H-1", offset_minutes_before=60, template_name="booking_reminder_h1"),
        ReminderRule(name="Disabled", enabled=False, offset_minutes_before=30),
    ]

    reminders = create_reminders_for_booking(
        booking,
        rules,
        now=datetime(2026, 4, 29, 9, 0, tzinfo=timezone.utc),
    )

    assert [r.kind for r in reminders] == ["J-1", "H-1"]
    assert [r.scheduled_for for r in reminders] == [
        appointment - timedelta(days=1),
        appointment - timedelta(hours=1),
    ]
    assert all(isinstance(r, BookingReminder) for r in reminders)
    assert all(r.status == "pending" for r in reminders)


def test_reminders_are_not_generated_for_cancelled_or_past_times():
    appointment = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    rule = ReminderRule(name="H-1", offset_minutes_before=60)

    cancelled = BookingRecord(
        phone="212665883062",
        status="customer_cancelled",
        appointment_start_at=appointment,
    )
    assert create_reminders_for_booking(cancelled, [rule], now=datetime(2026, 4, 30, tzinfo=timezone.utc)) == []

    confirmed = BookingRecord(
        phone="212665883062",
        status="confirmed",
        appointment_start_at=appointment,
    )
    assert create_reminders_for_booking(
        confirmed,
        [rule],
        now=datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc),
    ) == []
