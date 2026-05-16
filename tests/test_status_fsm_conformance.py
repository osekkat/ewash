from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import init_db, make_engine, session_scope
from app.models import (
    ALLOWED_STATUS_TRANSITIONS,
    BOOKING_STATUSES,
    FINAL_BOOKING_STATUSES,
    BookingReminderRow,
    BookingRow,
    BookingStatusEventRow,
    Customer,
    transition_booking_status,
)


SPEC_STATUSES = tuple(ALLOWED_STATUS_TRANSITIONS)
STATUS_PAIRS = [
    (from_index, to_index, from_status, to_status)
    for from_index, from_status in enumerate(SPEC_STATUSES)
    for to_index, to_status in enumerate(SPEC_STATUSES)
]
NOW = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)


def test_allowed_status_transition_spec_covers_booking_status_catalog():
    assert set(SPEC_STATUSES) == set(BOOKING_STATUSES)
    assert set().union(*ALLOWED_STATUS_TRANSITIONS.values()).issubset(SPEC_STATUSES)


@pytest.mark.parametrize(
    ("from_index", "to_index", "from_status", "to_status"),
    STATUS_PAIRS,
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_transition_booking_status_conforms_to_allowed_status_transition_spec(
    from_index: int,
    to_index: int,
    from_status: str,
    to_status: str,
):
    if to_status in ALLOWED_STATUS_TRANSITIONS[from_status]:
        _assert_allowed_transition_persists_and_fires_side_effects(
            from_index,
            to_index,
            from_status,
            to_status,
        )
    else:
        _assert_disallowed_transition_leaves_database_unchanged(
            from_index,
            to_index,
            from_status,
            to_status,
        )


def _assert_allowed_transition_persists_and_fires_side_effects(
    from_index: int,
    to_index: int,
    from_status: str,
    to_status: str,
) -> None:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    with session_scope(engine) as session:
        booking, pending_reminder_id, sent_reminder_id = _seed_booking_with_reminders(
            session,
            from_index,
            to_index,
            from_status,
        )
        booking_id = booking.id

        event = transition_booking_status(
            booking,
            to_status,
            actor="fsm-conformance",
            note=f"{from_status}->{to_status}",
            now=NOW,
        )
        assert isinstance(event, BookingStatusEventRow)
        assert event.from_status == from_status
        assert event.to_status == to_status
        assert event.actor == "fsm-conformance"
        session.flush()

    with session_scope(engine) as session:
        saved = session.get(BookingRow, booking_id)
        assert saved is not None
        assert saved.status == to_status
        assert saved.updated_at.replace(tzinfo=timezone.utc) == NOW

        events = session.scalars(
            select(BookingStatusEventRow).where(BookingStatusEventRow.booking_id == booking_id)
        ).all()
        assert [(event.from_status, event.to_status, event.actor, event.note) for event in events] == [
            (from_status, to_status, "fsm-conformance", f"{from_status}->{to_status}")
        ]

        pending_reminder = session.get(BookingReminderRow, pending_reminder_id)
        sent_reminder = session.get(BookingReminderRow, sent_reminder_id)
        assert pending_reminder is not None
        assert sent_reminder is not None
        if to_status in FINAL_BOOKING_STATUSES:
            assert pending_reminder.status == "cancelled"
            assert pending_reminder.error == f"booking_status:{to_status}"
        else:
            assert pending_reminder.status == "pending"
            assert pending_reminder.error == ""
        assert sent_reminder.status == "sent"
        assert sent_reminder.error == "already sent"


def _assert_disallowed_transition_leaves_database_unchanged(
    from_index: int,
    to_index: int,
    from_status: str,
    to_status: str,
) -> None:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)

    with session_scope(engine) as session:
        booking, pending_reminder_id, sent_reminder_id = _seed_booking_with_reminders(
            session,
            from_index,
            to_index,
            from_status,
        )
        booking_id = booking.id

        with pytest.raises(ValueError):
            transition_booking_status(
                booking,
                to_status,
                actor="fsm-conformance",
                note=f"{from_status}->{to_status}",
                now=NOW,
            )
        session.flush()

    with session_scope(engine) as session:
        saved = session.get(BookingRow, booking_id)
        assert saved is not None
        assert saved.status == from_status
        assert saved.updated_at is not None
        assert session.scalars(
            select(BookingStatusEventRow).where(BookingStatusEventRow.booking_id == booking_id)
        ).all() == []

        pending_reminder = session.get(BookingReminderRow, pending_reminder_id)
        sent_reminder = session.get(BookingReminderRow, sent_reminder_id)
        assert pending_reminder is not None
        assert sent_reminder is not None
        assert pending_reminder.status == "pending"
        assert pending_reminder.error == ""
        assert sent_reminder.status == "sent"
        assert sent_reminder.error == "already sent"


def _seed_booking_with_reminders(
    session,
    from_index: int,
    to_index: int,
    status: str,
) -> tuple[BookingRow, int, int]:
    suffix = f"{from_index:02d}{to_index:02d}"
    phone = f"2126000{suffix}"
    session.add(Customer(phone=phone, display_name="FSM"))
    booking = BookingRow(
        ref=f"EW-2026-FSM-{suffix}",
        customer_phone=phone,
        status=status,
        appointment_start_at=NOW + timedelta(days=3),
    )
    session.add(booking)
    session.flush()

    pending_reminder = BookingReminderRow(
        booking_id=booking.id,
        rule_id=None,
        kind="conformance-pending",
        scheduled_for=NOW + timedelta(days=2),
        status="pending",
    )
    sent_reminder = BookingReminderRow(
        booking_id=booking.id,
        rule_id=None,
        kind="conformance-sent",
        scheduled_for=NOW + timedelta(days=1),
        sent_at=NOW,
        status="sent",
        error="already sent",
    )
    session.add_all([pending_reminder, sent_reminder])
    session.flush()
    return booking, int(pending_reminder.id), int(sent_reminder.id)
