"""Reminder dispatcher for H-2 BookingReminderRow rows.

``confirm_booking_by_ewash`` writes a BookingReminderRow at H-2 when staff
promotes a booking to ``confirmed``. Without a sender those rows accumulate and
customers never get pinged. This module fills that gap with a thin polling
endpoint protected by ``X-Internal-Cron-Secret``, intended to be hit by Railway
Cron or any external scheduler on a 5–10 minute cadence.

Design constraints from AGENTS.md (FastAPI + asyncio mandate):
* Single-process polling loop, no celery/rq/dramatiq/apscheduler.
* Async-first via ``httpx.AsyncClient`` (the underlying ``meta.send_template``).
* Atomic claim semantics via ``SELECT ... FOR UPDATE SKIP LOCKED`` (Postgres)
  in :func:`app.persistence.claim_next_due_reminder`, so multiple cron firings
  don't double-send.
"""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from fastapi import APIRouter, Header, HTTPException, Query

from . import meta
from .config import settings
from .persistence import (
    ReminderDispatchCandidate,
    claim_next_due_reminder,
    mark_reminder_failed,
    mark_reminder_sent,
    skip_reminder_if_booking_not_sendable,
)

log = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_BATCH_SIZE = 50
MAX_BATCH_SIZE = 200
REMINDER_SEND_ALLOWED_BOOKING_STATUSES = ("confirmed",)


@dataclass(frozen=True)
class DispatchResult:
    """Counts emitted per :func:`dispatch_pending_reminders` invocation."""
    sent: int = 0
    failed: int = 0
    examined: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"sent": self.sent, "failed": self.failed, "examined": self.examined}


def _reminder_template_parameters(candidate: ReminderDispatchCandidate) -> list[str]:
    """Six positional template params: ref, name, service, date, slot, location.

    Mirrors the order of the ``booking_reminder_h2`` template the seed
    ReminderRuleRow contemplates. Staff configures the template body in the
    Meta dashboard; this code only guarantees the parameter order.
    """
    return [
        candidate.booking_ref or "-",
        candidate.customer_name or "-",
        candidate.service_label or "-",
        candidate.date_label or "-",
        candidate.slot or "-",
        candidate.location_label or "-",
    ]


async def _send_one(candidate: ReminderDispatchCandidate) -> tuple[bool, str]:
    """Send a single reminder. Returns (success, error_text)."""
    if not candidate.customer_phone:
        return False, "missing customer_phone"
    if not candidate.template_name:
        return False, "missing template_name"
    blocking_reason = skip_reminder_if_booking_not_sendable(
        candidate.reminder_id,
        allowed_booking_statuses=REMINDER_SEND_ALLOWED_BOOKING_STATUSES,
    )
    if blocking_reason is not None:
        return False, blocking_reason
    try:
        await meta.send_template(
            candidate.customer_phone,
            candidate.template_name,
            language_code=candidate.template_language or "fr",
            body_parameters=_reminder_template_parameters(candidate),
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:1500]
    return True, ""


async def dispatch_pending_reminders(
    *,
    now: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> DispatchResult:
    """Claim and send pending reminders up to ``batch_size`` rows.

    Loops calling :func:`claim_next_due_reminder` (each call is its own short
    transaction with FOR UPDATE SKIP LOCKED on Postgres) until either the
    batch cap is reached or no more rows are eligible.
    """
    capped = max(1, min(batch_size, MAX_BATCH_SIZE))
    sent = 0
    failed = 0
    examined = 0
    seen_ids: set[int] = set()
    while examined < capped:
        candidate = claim_next_due_reminder(now=now, exclude_ids=seen_ids)
        if candidate is None:
            break
        seen_ids.add(candidate.reminder_id)
        examined += 1
        started = time.perf_counter()
        success, error = await _send_one(candidate)
        duration_ms = (time.perf_counter() - started) * 1000
        if success:
            mark_reminder_sent(candidate.reminder_id, now=now)
            sent += 1
            log.info(
                "reminders.dispatch sent reminder_id=%d ref=%s kind=%s "
                "attempt=%d/%d duration_ms=%.1f",
                candidate.reminder_id,
                candidate.booking_ref,
                candidate.kind,
                candidate.attempt_count,
                candidate.max_sends,
                duration_ms,
            )
        else:
            mark_reminder_failed(candidate.reminder_id, error=error)
            failed += 1
            log.error(
                "reminders.dispatch failed reminder_id=%d ref=%s kind=%s "
                "attempt=%d/%d duration_ms=%.1f error=%s",
                candidate.reminder_id,
                candidate.booking_ref,
                candidate.kind,
                candidate.attempt_count,
                candidate.max_sends,
                duration_ms,
                error,
            )
    return DispatchResult(sent=sent, failed=failed, examined=examined)


@router.post("/internal/reminders/dispatch")
async def dispatch_reminders_endpoint(
    batch_size: int = Query(default=DEFAULT_BATCH_SIZE, ge=1, le=MAX_BATCH_SIZE),
    x_internal_cron_secret: str | None = Header(default=None, alias="X-Internal-Cron-Secret"),
) -> dict[str, int]:
    """Cron-triggered reminder dispatch endpoint.

    Auth: matches the existing ``/internal/conversations/abandon`` pattern —
    requires the ``X-Internal-Cron-Secret`` header to equal
    ``settings.internal_cron_secret``. A missing or unconfigured secret yields
    503 (so misconfigured deployments fail loudly rather than silently
    accepting unauthenticated calls).
    """
    if not settings.internal_cron_secret:
        raise HTTPException(status_code=503, detail="Internal cron is not configured")
    if not secrets.compare_digest(x_internal_cron_secret or "", settings.internal_cron_secret):
        raise HTTPException(status_code=403, detail="Forbidden")
    result = await dispatch_pending_reminders(batch_size=batch_size)
    return result.as_dict()
