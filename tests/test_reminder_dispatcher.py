"""Tests for the H-2 reminder dispatcher (ewash-b8w).

Covers the persistence claim semantics, the async dispatch loop, the
``/internal/reminders/dispatch`` HTTP surface, and the failure / retry edge
cases enumerated in the bead acceptance criteria.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import meta as meta_module
from app import reminders as reminders_module
from app.config import settings
from app.db import init_db, make_engine, session_scope
from app.main import app
from app.models import BookingReminderRow, BookingRow, ReminderRuleRow
from app.persistence import (
    _configured_engine,
    claim_next_due_reminder,
    confirm_booking_by_ewash,
    mark_reminder_failed,
    mark_reminder_sent,
    persist_confirmed_booking,
)
from app.reminders import (
    DispatchResult,
    dispatch_pending_reminders,
)

from tests.test_booking_persistence import _sample_booking


def _setup_confirmed_booking_with_reminder(
    engine,
    *,
    phone: str = "212600009001",
    appointment_at: datetime | None = None,
    rule_kwargs: dict | None = None,
):
    """Create a confirmed booking + a past-due pending reminder row.

    Returns ``(booking_ref, reminder_id, rule_id)``.
    """
    appointment_at = appointment_at or (datetime.now(timezone.utc) + timedelta(hours=10))
    booking = _sample_booking(phone=phone)
    booking.date_iso = appointment_at.date().isoformat()
    persist_confirmed_booking(booking, engine=engine)

    defaults = {
        "name": "H-2",
        "enabled": True,
        "offset_minutes_before": 120,
        "max_sends": 1,
        "min_minutes_between_sends": 0,
        "template_name": "booking_reminder_h2",
    }
    defaults.update(rule_kwargs or {})

    with session_scope(engine) as session:
        rule = ReminderRuleRow(**defaults)
        session.add(rule)
        session.flush()
        rule_id = int(rule.id)

        row = session.scalars(select(BookingRow).where(BookingRow.ref == booking.ref)).one()
        row.status = "confirmed"
        row.appointment_start_at = appointment_at

        # Past-due reminder — scheduled an hour ago.
        reminder = BookingReminderRow(
            booking_id=row.id,
            rule_id=rule_id,
            kind="H-2",
            scheduled_for=datetime.now(timezone.utc) - timedelta(hours=1),
            status="pending",
        )
        session.add(reminder)
        session.flush()
        reminder_id = int(reminder.id)

    return booking.ref, reminder_id, rule_id


@pytest.fixture
def _patch_engine(monkeypatch, tmp_path):
    """Plant a tmp-path-backed engine as the global persistence engine."""
    db_url = f"sqlite+pysqlite:///{tmp_path / 'reminders.db'}"
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    engine = make_engine(db_url)
    init_db(engine)
    yield engine
    _configured_engine.cache_clear()


def test_claim_next_due_reminder_returns_eligible_pending_row(_patch_engine):
    ref, reminder_id, _ = _setup_confirmed_booking_with_reminder(_patch_engine)

    candidate = claim_next_due_reminder()

    assert candidate is not None
    assert candidate.reminder_id == reminder_id
    assert candidate.booking_ref == ref
    assert candidate.template_name == "booking_reminder_h2"
    assert candidate.attempt_count == 1  # claim increments
    assert candidate.max_sends == 1

    with session_scope(_patch_engine) as session:
        row = session.get(BookingReminderRow, reminder_id)
        # Claim stamps sent_at as an in-flight marker; status stays pending
        # until the caller transitions to sent/failed.
        assert row.attempt_count == 1
        assert row.sent_at is not None
        assert row.status == "pending"


def test_claim_skips_future_scheduled_rows(_patch_engine):
    _, reminder_id, _ = _setup_confirmed_booking_with_reminder(_patch_engine)
    with session_scope(_patch_engine) as session:
        row = session.get(BookingReminderRow, reminder_id)
        row.scheduled_for = datetime.now(timezone.utc) + timedelta(hours=2)

    assert claim_next_due_reminder() is None


def test_claim_skips_already_sent_rows(_patch_engine):
    _, reminder_id, _ = _setup_confirmed_booking_with_reminder(_patch_engine)
    mark_reminder_sent(reminder_id)

    assert claim_next_due_reminder() is None

    with session_scope(_patch_engine) as session:
        row = session.get(BookingReminderRow, reminder_id)
        assert row.status == "sent"


def test_claim_marks_failed_when_max_sends_exceeded(_patch_engine):
    _, reminder_id, _ = _setup_confirmed_booking_with_reminder(_patch_engine)
    # Simulate a prior failed attempt that already consumed the only allowed send.
    with session_scope(_patch_engine) as session:
        row = session.get(BookingReminderRow, reminder_id)
        row.attempt_count = 1
        row.status = "failed"
        row.error = "first attempt failed"

    candidate = claim_next_due_reminder()

    assert candidate is None
    with session_scope(_patch_engine) as session:
        row = session.get(BookingReminderRow, reminder_id)
        assert row.status == "failed"
        assert row.attempt_count == 1


def test_exhausted_failed_reminder_does_not_block_later_due_row(_patch_engine):
    _, exhausted_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        phone="212600009010",
    )
    _, eligible_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        phone="212600009011",
    )
    now = datetime.now(timezone.utc)
    with session_scope(_patch_engine) as session:
        exhausted = session.get(BookingReminderRow, exhausted_id)
        exhausted.status = "failed"
        exhausted.attempt_count = 1
        exhausted.scheduled_for = now - timedelta(hours=2)
        exhausted.error = "permanent template failure"

        eligible = session.get(BookingReminderRow, eligible_id)
        eligible.scheduled_for = now - timedelta(hours=1)

    candidate = claim_next_due_reminder()

    assert candidate is not None
    assert candidate.reminder_id == eligible_id


def test_claim_defers_inside_min_minutes_between_sends(_patch_engine):
    _, reminder_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        rule_kwargs={"max_sends": 3, "min_minutes_between_sends": 30},
    )
    just_now = datetime.now(timezone.utc)
    with session_scope(_patch_engine) as session:
        row = session.get(BookingReminderRow, reminder_id)
        row.status = "failed"
        row.attempt_count = 1
        row.sent_at = just_now - timedelta(minutes=5)
        row.error = "transient meta failure"

    assert claim_next_due_reminder() is None

    with session_scope(_patch_engine) as session:
        row = session.get(BookingReminderRow, reminder_id)
        # Still pickable after the cooldown lapses.
        row.sent_at = just_now - timedelta(minutes=31)

    assert claim_next_due_reminder() is not None


def test_failed_reminder_inside_cooldown_does_not_block_later_due_row(_patch_engine):
    _, cooling_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        phone="212600009020",
        rule_kwargs={"max_sends": 3, "min_minutes_between_sends": 30},
    )
    _, eligible_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        phone="212600009021",
    )
    now = datetime.now(timezone.utc)
    with session_scope(_patch_engine) as session:
        cooling = session.get(BookingReminderRow, cooling_id)
        cooling.status = "failed"
        cooling.attempt_count = 1
        cooling.sent_at = now - timedelta(minutes=5)
        cooling.scheduled_for = now - timedelta(hours=2)
        cooling.error = "transient meta failure"

        eligible = session.get(BookingReminderRow, eligible_id)
        eligible.scheduled_for = now - timedelta(hours=1)

    candidate = claim_next_due_reminder()

    assert candidate is not None
    assert candidate.reminder_id == eligible_id


def test_claim_skips_bookings_not_in_confirmed_status(_patch_engine):
    ref, _, _ = _setup_confirmed_booking_with_reminder(_patch_engine)
    with session_scope(_patch_engine) as session:
        row = session.scalars(select(BookingRow).where(BookingRow.ref == ref)).one()
        row.status = "customer_cancelled"

    assert claim_next_due_reminder() is None


def test_mark_sent_rechecks_booking_status_after_in_flight_cancellation(_patch_engine):
    ref, reminder_id, _ = _setup_confirmed_booking_with_reminder(_patch_engine)
    candidate = claim_next_due_reminder()
    assert candidate is not None

    with session_scope(_patch_engine) as session:
        booking = session.scalars(select(BookingRow).where(BookingRow.ref == ref)).one()
        booking.status = "customer_cancelled"

    mark_reminder_sent(reminder_id)

    with session_scope(_patch_engine) as session:
        row = session.get(BookingReminderRow, reminder_id)
        assert row.status == "pending"
        assert row.booking.status == "customer_cancelled"


def test_in_flight_pending_reminder_does_not_block_later_due_row(_patch_engine):
    _, in_flight_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        phone="212600009030",
        rule_kwargs={"max_sends": 2, "min_minutes_between_sends": 0},
    )
    _, eligible_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        phone="212600009031",
    )
    now = datetime.now(timezone.utc)
    with session_scope(_patch_engine) as session:
        in_flight = session.get(BookingReminderRow, in_flight_id)
        in_flight.status = "pending"
        in_flight.attempt_count = 1
        in_flight.sent_at = now
        in_flight.scheduled_for = now - timedelta(hours=2)

        eligible = session.get(BookingReminderRow, eligible_id)
        eligible.scheduled_for = now - timedelta(hours=1)

    candidate = claim_next_due_reminder()

    assert candidate is not None
    assert candidate.reminder_id == eligible_id


def test_concurrent_claim_does_not_double_pick_same_row(_patch_engine):
    """Sequential claims (mocking concurrent firings) should not re-pick the same row.

    On Postgres the FOR UPDATE SKIP LOCKED clause is what actually buys
    cross-process safety; on SQLite we verify the in-process predicate
    correctly excludes the just-claimed row (status='pending' AND sent_at
    IS NULL is the eligibility filter for un-tried rows, and 'failed'+cooldown
    for retries — neither matches a freshly claimed in-flight row).
    """
    _setup_confirmed_booking_with_reminder(_patch_engine)
    first = claim_next_due_reminder()
    second = claim_next_due_reminder()

    assert first is not None
    assert second is None


def test_claim_does_not_repick_pending_in_flight_retryable_row(_patch_engine):
    """A claimed pending row is in-flight even when max_sends allows retries."""
    _, reminder_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        rule_kwargs={"max_sends": 2, "min_minutes_between_sends": 0},
    )

    first = claim_next_due_reminder()
    second = claim_next_due_reminder()

    assert first is not None
    assert second is None
    with session_scope(_patch_engine) as session:
        row = session.get(BookingReminderRow, reminder_id)
        assert row.status == "pending"
        assert row.sent_at is not None
        assert row.attempt_count == 1


def test_claim_recovers_stale_pending_in_flight_row(_patch_engine):
    """A crashed sender should not strand a retryable claimed row forever."""
    now = datetime.now(timezone.utc)
    _, reminder_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        rule_kwargs={"max_sends": 2, "min_minutes_between_sends": 0},
    )

    first = claim_next_due_reminder(now=now)
    too_soon = claim_next_due_reminder(now=now + timedelta(minutes=4, seconds=59))
    stale_retry = claim_next_due_reminder(now=now + timedelta(minutes=5, seconds=1))

    assert first is not None
    assert too_soon is None
    assert stale_retry is not None
    assert stale_retry.reminder_id == reminder_id
    assert stale_retry.attempt_count == 2


def test_claim_sql_uses_for_update_skip_locked_on_postgresql():
    from sqlalchemy import select as _select
    from sqlalchemy.dialects import postgresql

    stmt = (
        _select(BookingReminderRow)
        .join(BookingRow, BookingReminderRow.booking_id == BookingRow.id)
        .where(BookingReminderRow.status == "pending")
        .with_for_update(skip_locked=True)
    )
    rendered = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in rendered
    assert "SKIP LOCKED" in rendered


def test_dispatch_pending_reminders_sends_and_marks_sent(monkeypatch, _patch_engine):
    _, reminder_id, _ = _setup_confirmed_booking_with_reminder(_patch_engine)

    sent_calls: list[dict] = []

    async def fake_send_template(to, template_name, *, language_code="fr", body_parameters=None):
        sent_calls.append(
            {
                "to": to,
                "template_name": template_name,
                "language_code": language_code,
                "body_parameters": list(body_parameters or []),
            }
        )
        return {"ok": True}

    monkeypatch.setattr(meta_module, "send_template", fake_send_template)

    result = asyncio.run(dispatch_pending_reminders(batch_size=10))

    assert isinstance(result, DispatchResult)
    assert result.sent == 1
    assert result.failed == 0
    assert result.examined == 1
    assert len(sent_calls) == 1
    call = sent_calls[0]
    assert call["template_name"] == "booking_reminder_h2"
    assert call["language_code"] == "fr"
    assert len(call["body_parameters"]) == 6

    with session_scope(_patch_engine) as session:
        row = session.get(BookingReminderRow, reminder_id)
        assert row.status == "sent"
        assert row.error == ""


def test_dispatch_cooldown_row_does_not_block_later_due_reminder(monkeypatch, _patch_engine):
    first_ref, first_reminder_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        phone="212600009110",
        rule_kwargs={"max_sends": 3, "min_minutes_between_sends": 30},
    )
    second_ref, second_reminder_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        phone="212600009111",
    )
    now = datetime.now(timezone.utc)
    with session_scope(_patch_engine) as session:
        first = session.get(BookingReminderRow, first_reminder_id)
        first.status = "failed"
        first.attempt_count = 1
        first.sent_at = now - timedelta(minutes=5)
        first.scheduled_for = now - timedelta(hours=3)
        second = session.get(BookingReminderRow, second_reminder_id)
        second.scheduled_for = now - timedelta(hours=1)

    sent_refs: list[str] = []

    async def fake_send_template(to, template_name, *, language_code="fr", body_parameters=None):
        sent_refs.append(list(body_parameters or [])[0])
        return {"ok": True}

    monkeypatch.setattr(meta_module, "send_template", fake_send_template)

    result = asyncio.run(dispatch_pending_reminders(now=now, batch_size=10))

    assert result.sent == 1
    assert result.failed == 0
    assert result.examined == 1
    assert sent_refs == [second_ref]
    with session_scope(_patch_engine) as session:
        first = session.get(BookingReminderRow, first_reminder_id)
        second = session.get(BookingReminderRow, second_reminder_id)
        assert first.status == "failed"
        assert first.attempt_count == 1
        assert second.status == "sent"
    assert first_ref != second_ref


def test_dispatch_exhausted_failed_row_does_not_block_later_due_reminder(monkeypatch, _patch_engine):
    _, exhausted_reminder_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        phone="212600009112",
    )
    second_ref, second_reminder_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        phone="212600009113",
    )
    now = datetime.now(timezone.utc)
    with session_scope(_patch_engine) as session:
        exhausted = session.get(BookingReminderRow, exhausted_reminder_id)
        exhausted.status = "failed"
        exhausted.attempt_count = 1
        exhausted.sent_at = now - timedelta(hours=2)
        exhausted.scheduled_for = now - timedelta(hours=3)
        second = session.get(BookingReminderRow, second_reminder_id)
        second.scheduled_for = now - timedelta(hours=1)

    sent_refs: list[str] = []

    async def fake_send_template(to, template_name, *, language_code="fr", body_parameters=None):
        sent_refs.append(list(body_parameters or [])[0])
        return {"ok": True}

    monkeypatch.setattr(meta_module, "send_template", fake_send_template)

    result = asyncio.run(dispatch_pending_reminders(now=now, batch_size=10))

    assert result.sent == 1
    assert result.failed == 0
    assert result.examined == 1
    assert sent_refs == [second_ref]
    with session_scope(_patch_engine) as session:
        exhausted = session.get(BookingReminderRow, exhausted_reminder_id)
        second = session.get(BookingReminderRow, second_reminder_id)
        assert exhausted.status == "failed"
        assert exhausted.attempt_count == 1
        assert second.status == "sent"


def test_dispatch_exhausted_stale_pending_row_does_not_block_later_due_reminder(monkeypatch, _patch_engine):
    _, exhausted_reminder_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        phone="212600009114",
    )
    second_ref, second_reminder_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        phone="212600009115",
    )
    now = datetime.now(timezone.utc)
    with session_scope(_patch_engine) as session:
        exhausted = session.get(BookingReminderRow, exhausted_reminder_id)
        exhausted.status = "pending"
        exhausted.attempt_count = 1
        exhausted.sent_at = now - timedelta(minutes=10)
        exhausted.scheduled_for = now - timedelta(hours=3)
        second = session.get(BookingReminderRow, second_reminder_id)
        second.scheduled_for = now - timedelta(hours=1)

    sent_refs: list[str] = []

    async def fake_send_template(to, template_name, *, language_code="fr", body_parameters=None):
        sent_refs.append(list(body_parameters or [])[0])
        return {"ok": True}

    monkeypatch.setattr(meta_module, "send_template", fake_send_template)

    result = asyncio.run(dispatch_pending_reminders(now=now, batch_size=10))

    assert result.sent == 1
    assert result.failed == 0
    assert result.examined == 1
    assert sent_refs == [second_ref]
    with session_scope(_patch_engine) as session:
        exhausted = session.get(BookingReminderRow, exhausted_reminder_id)
        second = session.get(BookingReminderRow, second_reminder_id)
        assert exhausted.status == "failed"
        assert exhausted.error == "max_sends exhausted"
        assert second.status == "sent"


def test_mark_sent_does_not_override_cancelled_in_flight_reminder(_patch_engine):
    ref, reminder_id, _ = _setup_confirmed_booking_with_reminder(_patch_engine)
    candidate = claim_next_due_reminder()
    assert candidate is not None
    assert candidate.booking_ref == ref

    with session_scope(_patch_engine) as session:
        reminder = session.get(BookingReminderRow, reminder_id)
        reminder.status = "cancelled"
        reminder.error = "booking_status:admin_cancelled"
        reminder.booking.status = "admin_cancelled"

    mark_reminder_sent(reminder_id)

    with session_scope(_patch_engine) as session:
        reminder = session.get(BookingReminderRow, reminder_id)
        assert reminder.status == "cancelled"
        assert reminder.error == "booking_status:admin_cancelled"


def test_dispatch_marks_failed_when_meta_send_raises(monkeypatch, _patch_engine):
    _, reminder_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        rule_kwargs={"max_sends": 2, "min_minutes_between_sends": 0},
    )

    async def boom(*args, **kwargs):
        raise RuntimeError("Meta is sad")

    monkeypatch.setattr(meta_module, "send_template", boom)

    result = asyncio.run(dispatch_pending_reminders(batch_size=10))

    assert result.sent == 0
    assert result.failed == 1
    assert result.examined == 1

    with session_scope(_patch_engine) as session:
        row = session.get(BookingReminderRow, reminder_id)
        assert row.status == "failed"
        assert "RuntimeError" in row.error
        assert row.attempt_count == 1


def test_dispatch_is_a_noop_when_no_due_rows(monkeypatch, _patch_engine):
    """No reminder rows → 0 sends, 0 failures, 0 examined."""
    calls = 0

    async def should_not_be_called(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {}

    monkeypatch.setattr(meta_module, "send_template", should_not_be_called)

    result = asyncio.run(dispatch_pending_reminders(batch_size=10))

    assert (result.sent, result.failed, result.examined) == (0, 0, 0)
    assert calls == 0


def test_dispatch_endpoint_requires_internal_cron_secret(monkeypatch, _patch_engine):
    """Missing or wrong X-Internal-Cron-Secret → 403."""
    monkeypatch.setattr(settings, "internal_cron_secret", "cron-secret-123")
    _setup_confirmed_booking_with_reminder(_patch_engine)

    async def fake_send_template(*args, **kwargs):
        return {"ok": True}

    monkeypatch.setattr(meta_module, "send_template", fake_send_template)
    client = TestClient(app)

    no_header = client.post("/internal/reminders/dispatch")
    wrong_header = client.post(
        "/internal/reminders/dispatch",
        headers={"X-Internal-Cron-Secret": "nope"},
    )
    good_header = client.post(
        "/internal/reminders/dispatch",
        headers={"X-Internal-Cron-Secret": "cron-secret-123"},
    )

    assert no_header.status_code == 403
    assert wrong_header.status_code == 403
    assert good_header.status_code == 200
    assert good_header.json() == {"sent": 1, "failed": 0, "examined": 1}


def test_dispatch_endpoint_503_when_internal_cron_secret_unconfigured(monkeypatch, _patch_engine):
    """Unconfigured secret yields 503 so misconfig fails loud, not silent-open."""
    monkeypatch.setattr(settings, "internal_cron_secret", "")
    client = TestClient(app)

    response = client.post(
        "/internal/reminders/dispatch",
        headers={"X-Internal-Cron-Secret": "anything"},
    )

    assert response.status_code == 503


def test_dispatch_endpoint_respects_batch_size_query(monkeypatch, _patch_engine):
    """Multiple due reminders, batch_size=1 caps the work per call."""
    monkeypatch.setattr(settings, "internal_cron_secret", "cron-secret-123")
    _setup_confirmed_booking_with_reminder(_patch_engine, phone="212600009100")
    _setup_confirmed_booking_with_reminder(_patch_engine, phone="212600009101")

    sent = 0

    async def fake_send_template(*args, **kwargs):
        nonlocal sent
        sent += 1
        return {}

    monkeypatch.setattr(meta_module, "send_template", fake_send_template)
    client = TestClient(app)

    first = client.post(
        "/internal/reminders/dispatch?batch_size=1",
        headers={"X-Internal-Cron-Secret": "cron-secret-123"},
    )
    second = client.post(
        "/internal/reminders/dispatch?batch_size=1",
        headers={"X-Internal-Cron-Secret": "cron-secret-123"},
    )

    assert first.json() == {"sent": 1, "failed": 0, "examined": 1}
    assert second.json() == {"sent": 1, "failed": 0, "examined": 1}
    assert sent == 2


def test_dispatch_retries_failed_row_until_max_sends(monkeypatch, _patch_engine):
    """A failed row stays eligible until attempt_count == max_sends."""
    _, reminder_id, _ = _setup_confirmed_booking_with_reminder(
        _patch_engine,
        rule_kwargs={"max_sends": 2, "min_minutes_between_sends": 0},
    )

    call_count = 0

    async def first_fails_then_succeeds(to, template_name, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient")
        return {"ok": True}

    monkeypatch.setattr(meta_module, "send_template", first_fails_then_succeeds)

    result_a = asyncio.run(dispatch_pending_reminders(batch_size=10))
    assert (result_a.sent, result_a.failed, result_a.examined) == (0, 1, 1)

    result_b = asyncio.run(dispatch_pending_reminders(batch_size=10))
    assert (result_b.sent, result_b.failed, result_b.examined) == (1, 0, 1)

    with session_scope(_patch_engine) as session:
        row = session.get(BookingReminderRow, reminder_id)
        assert row.status == "sent"
        assert row.attempt_count == 2
