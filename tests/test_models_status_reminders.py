from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
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
