"""Golden regression tests for the reminder dispatcher pipeline."""
from __future__ import annotations

import asyncio
import copy
import difflib
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest
from sqlalchemy import and_, event, func, or_, select
from sqlalchemy.dialects import postgresql

from app import meta as meta_module
from app import reminders as reminders_module
from app.config import settings
from app.db import init_db, make_engine, session_scope
from app.models import BookingReminderRow, BookingRow, ReminderRuleRow
from app.persistence import (
    REMINDER_CLAIM_LEASE_MINUTES,
    _configured_engine,
    claim_next_due_reminder,
    confirm_booking_by_ewash,
    mark_reminder_sent,
    persist_confirmed_booking,
)
from app.reminders import dispatch_pending_reminders
from tests.test_booking_persistence import _sample_booking


GOLDEN_DIR = Path(__file__).parent / "golden" / "reminders"
FIXED_NOW = datetime(2026, 5, 16, 8, 0, tzinfo=timezone.utc)
BOOKING_REF_RE = re.compile(r"EW-\d{4}-\d+")


def _updating_goldens() -> bool:
    return os.environ.get("UPDATE_GOLDEN") == "1" or os.environ.get("UPDATE_GOLDENS") == "1"


def _assert_golden(path: Path, actual: str) -> None:
    actual_bytes = actual.encode("utf-8")
    if _updating_goldens() or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(actual_bytes)
        if not _updating_goldens():
            pytest.skip(f"created missing golden {path}; review and rerun")

    expected_bytes = path.read_bytes()
    if expected_bytes == actual_bytes:
        return

    expected = expected_bytes.decode("utf-8")
    diff = "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile=f"{path} (golden)",
            tofile=f"{path} (actual)",
            lineterm="",
        )
    )
    pytest.fail(f"golden drift in {path}\n{diff}")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _assert_golden_json(name: str, value: Any) -> None:
    _assert_golden(GOLDEN_DIR / name, _canonical_json(value))


def _scrub_booking_ref(value: str) -> str:
    return BOOKING_REF_RE.sub("[BOOKING_REF]", value or "")


def _scrub_timestamp(value: datetime | None) -> str | None:
    return "[TIMESTAMP]" if value is not None else None


def _scrub_meta_payload(payload: dict[str, Any]) -> dict[str, Any]:
    scrubbed = copy.deepcopy(payload)
    scrubbed["to"] = "[PHONE]"
    components = scrubbed.get("template", {}).get("components", [])
    for component in components:
        for parameter in component.get("parameters", []):
            if parameter.get("type") == "text":
                parameter["text"] = _scrub_booking_ref(str(parameter.get("text", "")))
    return scrubbed


def _snapshot_reminders(engine) -> list[dict[str, Any]]:
    with session_scope(engine) as session:
        rows = session.scalars(select(BookingReminderRow).order_by(BookingReminderRow.id)).all()
        snapshot: list[dict[str, Any]] = []
        for row in rows:
            booking = row.booking
            rule = row.rule
            snapshot.append(
                {
                    "id": "[ID]",
                    "booking_id": "[ID]",
                    "booking_ref": _scrub_booking_ref(booking.ref if booking is not None else ""),
                    "booking_status": booking.status if booking is not None else None,
                    "attempt_count": row.attempt_count,
                    "error": row.error or "",
                    "kind": row.kind,
                    "max_sends": rule.max_sends if rule is not None else 1,
                    "min_minutes_between_sends": (
                        rule.min_minutes_between_sends if rule is not None else 0
                    ),
                    "scheduled_for": _scrub_timestamp(row.scheduled_for),
                    "sent_at": _scrub_timestamp(row.sent_at),
                    "status": row.status,
                    "template_name": (
                        rule.template_name if rule is not None else "booking_reminder_h2"
                    ),
                }
            )
        return snapshot


@contextmanager
def _capture_sql(engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ) -> None:
        del conn, cursor, parameters, context, executemany
        canonical = re.sub(r"\s+", " ", statement).strip()
        if canonical:
            statements.append(canonical)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


def _format_sql(statements: list[str]) -> str:
    return "\n\n".join(
        f"-- statement {index:02d}\n{statement};"
        for index, statement in enumerate(statements, start=1)
    ) + "\n"


def _postgres_claim_lock_contract_sql() -> str:
    max_sends_expr = func.coalesce(ReminderRuleRow.max_sends, 1)
    attempts_expr = func.coalesce(BookingReminderRow.attempt_count, 0)
    stale_claim_before = FIXED_NOW - timedelta(minutes=REMINDER_CLAIM_LEASE_MINUTES)
    stmt = (
        select(BookingReminderRow)
        .join(BookingRow, BookingReminderRow.booking_id == BookingRow.id)
        .outerjoin(ReminderRuleRow, BookingReminderRow.rule_id == ReminderRuleRow.id)
        .where(
            BookingReminderRow.scheduled_for <= FIXED_NOW,
            BookingRow.status == "confirmed",
            or_(
                and_(
                    BookingReminderRow.status == "pending",
                    or_(
                        BookingReminderRow.sent_at.is_(None),
                        BookingReminderRow.sent_at <= stale_claim_before,
                    ),
                ),
                and_(
                    BookingReminderRow.status == "failed",
                    attempts_expr < max_sends_expr,
                ),
            ),
        )
        .order_by(BookingReminderRow.scheduled_for.asc(), BookingReminderRow.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    return _format_sql([re.sub(r"\s+", " ", sql).strip()])


def _setup_confirmed_booking_with_reminder(
    engine,
    *,
    phone: str = "212600009001",
    appointment_at: datetime | None = None,
    scheduled_for: datetime | None = None,
    rule_kwargs: dict[str, Any] | None = None,
) -> tuple[str, int, int]:
    appointment_at = appointment_at or (FIXED_NOW + timedelta(hours=4))
    booking = _sample_booking(phone=phone)
    booking.date_iso = appointment_at.date().isoformat()
    booking.date_label = appointment_at.date().isoformat()
    persist_confirmed_booking(booking, engine=engine)

    defaults: dict[str, Any] = {
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
        row.appointment_start_at = appointment_at
        row.appointment_end_at = appointment_at + timedelta(hours=2)
        row.date_label = appointment_at.date().isoformat()
        row.slot = "10h-12h"

    confirm_booking_by_ewash(booking.ref, engine=engine, now=FIXED_NOW)

    with session_scope(engine) as session:
        reminder = session.scalars(
            select(BookingReminderRow)
            .join(BookingRow)
            .where(BookingRow.ref == booking.ref)
            .order_by(BookingReminderRow.id.desc())
        ).first()
        assert reminder is not None
        reminder.scheduled_for = scheduled_for or (FIXED_NOW - timedelta(minutes=5))
        session.flush()
        reminder_id = int(reminder.id)

    return booking.ref, reminder_id, rule_id


@pytest.fixture
def golden_engine(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'reminder_golden.db'}"
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    engine = make_engine(db_url)
    init_db(engine)
    yield engine
    _configured_engine.cache_clear()


def test_reminder_sql_goldens(golden_engine):
    _assert_golden(
        GOLDEN_DIR / "claim_next_due_reminder_postgresql.sql",
        _postgres_claim_lock_contract_sql(),
    )

    _setup_confirmed_booking_with_reminder(golden_engine)
    with _capture_sql(golden_engine) as statements:
        candidate = claim_next_due_reminder(now=FIXED_NOW, engine=golden_engine)
    assert candidate is not None
    _assert_golden(GOLDEN_DIR / "claim_next_due_reminder.sql", _format_sql(statements))

    with _capture_sql(golden_engine) as statements:
        mark_reminder_sent(candidate.reminder_id, now=FIXED_NOW, engine=golden_engine)
    _assert_golden(GOLDEN_DIR / "mark_reminder_sent.sql", _format_sql(statements))

    _, recovery_reminder_id, _ = _setup_confirmed_booking_with_reminder(
        golden_engine,
        phone="212600009002",
        rule_kwargs={"max_sends": 2, "min_minutes_between_sends": 0},
    )
    with session_scope(golden_engine) as session:
        row = session.get(BookingReminderRow, recovery_reminder_id)
        assert row is not None
        row.status = "pending"
        row.attempt_count = 1
        row.sent_at = FIXED_NOW - timedelta(hours=2)
        row.scheduled_for = FIXED_NOW - timedelta(minutes=5)
        assert row.rule is not None
        row.rule.max_sends = 2
        row.rule.min_minutes_between_sends = 0
    with _capture_sql(golden_engine) as statements:
        recovered = claim_next_due_reminder(now=FIXED_NOW, engine=golden_engine)
    assert recovered is not None
    assert recovered.reminder_id == recovery_reminder_id
    _assert_golden(GOLDEN_DIR / "claim_recovery.sql", _format_sql(statements))


def test_meta_h2_payload_golden(monkeypatch, golden_engine):
    captured_payloads: list[dict[str, Any]] = []

    class FakeResponse:
        status_code = 200
        text = "{}"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"messages": [{"id": "golden-message"}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        async def post(self, url, *, headers, json):
            del url, headers
            captured_payloads.append(json)
            return FakeResponse()

    monkeypatch.setattr(meta_module.httpx, "AsyncClient", FakeAsyncClient)

    _setup_confirmed_booking_with_reminder(golden_engine, phone="212600009003")

    result = asyncio.run(dispatch_pending_reminders(now=FIXED_NOW, batch_size=10))

    assert result.as_dict() == {"sent": 1, "failed": 0, "examined": 1}
    assert len(captured_payloads) == 1
    _assert_golden_json(
        "meta_h2_payload.json",
        _scrub_meta_payload(captured_payloads[0]),
    )


def test_reminder_state_success_golden(monkeypatch, golden_engine):
    calls: list[dict[str, Any]] = []

    async def fake_send_template(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return {"messages": [{"id": "state-success"}]}

    monkeypatch.setattr(meta_module, "send_template", fake_send_template)
    _setup_confirmed_booking_with_reminder(golden_engine, phone="212600009004")

    actual = {
        "before": _snapshot_reminders(golden_engine),
    }
    result = asyncio.run(dispatch_pending_reminders(now=FIXED_NOW, batch_size=10))
    actual.update(
        {
            "after": _snapshot_reminders(golden_engine),
            "meta_call_count": len(calls),
            "result": result.as_dict(),
            "scenario": "success",
        }
    )

    _assert_golden_json("state_success.json", actual)


def test_reminder_state_cancelled_booking_skip_golden(monkeypatch, golden_engine):
    calls: list[dict[str, Any]] = []
    booking_ref, _, _ = _setup_confirmed_booking_with_reminder(
        golden_engine,
        phone="212600009005",
    )
    real_claim = reminders_module.claim_next_due_reminder

    def claim_then_cancel(*args, **kwargs):
        candidate = real_claim(*args, **kwargs)
        if candidate is not None:
            with session_scope(golden_engine) as session:
                booking = session.scalars(
                    select(BookingRow).where(BookingRow.ref == booking_ref)
                ).one()
                booking.status = "admin_cancelled"
        return candidate

    async def fake_send_template(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return {"messages": [{"id": "should-not-send"}]}

    monkeypatch.setattr(reminders_module, "claim_next_due_reminder", claim_then_cancel)
    monkeypatch.setattr(meta_module, "send_template", fake_send_template)

    actual = {
        "before": _snapshot_reminders(golden_engine),
    }
    result = asyncio.run(dispatch_pending_reminders(now=FIXED_NOW, batch_size=10))
    actual.update(
        {
            "after": _snapshot_reminders(golden_engine),
            "meta_call_count": len(calls),
            "result": result.as_dict(),
            "scenario": "cancelled-booking-skip",
        }
    )

    _assert_golden_json("state_cancelled_booking_skip.json", actual)


def test_reminder_state_retry_after_failure_golden(monkeypatch, golden_engine):
    calls = 0

    async def flaky_send_template(*args, **kwargs):
        nonlocal calls
        del args, kwargs
        calls += 1
        if calls == 1:
            raise RuntimeError("transient golden failure")
        return {"messages": [{"id": "state-retry"}]}

    monkeypatch.setattr(meta_module, "send_template", flaky_send_template)
    _setup_confirmed_booking_with_reminder(
        golden_engine,
        phone="212600009006",
        rule_kwargs={"max_sends": 2, "min_minutes_between_sends": 0},
    )

    actual = {
        "before": _snapshot_reminders(golden_engine),
    }
    first = asyncio.run(dispatch_pending_reminders(now=FIXED_NOW, batch_size=10))
    actual["after_failure"] = _snapshot_reminders(golden_engine)
    second = asyncio.run(dispatch_pending_reminders(now=FIXED_NOW, batch_size=10))
    actual.update(
        {
            "after_retry": _snapshot_reminders(golden_engine),
            "meta_call_count": calls,
            "results": [first.as_dict(), second.as_dict()],
            "scenario": "retry-after-failure",
        }
    )

    _assert_golden_json("state_retry_after_failure.json", actual)
