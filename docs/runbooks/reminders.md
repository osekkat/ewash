# Runbook: H-2 reminder dispatcher

Operational reference for the cron-driven worker that ships H-2
`BookingReminderRow` rows. Endpoint: `POST /internal/reminders/dispatch`.

## At a glance

| Item | Value |
|---|---|
| HTTP path | `POST /internal/reminders/dispatch` |
| Auth | `X-Internal-Cron-Secret` header (matches `INTERNAL_CRON_SECRET`) |
| Cadence | every 5 minutes (recommended) |
| Default batch size | 50 rows per call (override via `?batch_size=N`, capped at 200) |
| Response | `{"sent": N, "failed": N, "examined": N}` |
| Source | `app/reminders.py` |

## What it does

For each row in `booking_reminders` where:

- `status` is `pending` (or `failed` with attempts remaining)
- `scheduled_for <= now()`
- the parent booking is still `confirmed`
- the active `reminder_rules` row permits more sends (`attempt_count < max_sends`)
  and the cooldown (`min_minutes_between_sends`) has elapsed

the dispatcher:

1. Atomically claims the row (`SELECT ... FOR UPDATE SKIP LOCKED` on Postgres,
   row-level UPDATE on SQLite — see `app/persistence.py::claim_next_due_reminder`).
2. Sends the rule's `template_name` via `meta.send_template(...)` with body
   parameters `[ref, customer_name, service_label, date_label, slot, location_label]`.
3. Transitions the row to `sent` on success or `failed` on exception, recording
   the exception type and message in `error`.

Concurrent invocations (cron firings overlapping) cannot double-send: Postgres
returns disjoint row sets due to `SKIP LOCKED`, and the in-flight claim stamps
`sent_at` so the row no longer matches the eligibility predicate on the next
sweep.

## Scheduling — Railway

Until Railway exposes a first-class cron primitive on this project, drive the
endpoint from any external scheduler with a 5-minute cadence:

```bash
*/5 * * * * curl -sS -X POST \
    -H "X-Internal-Cron-Secret: $INTERNAL_CRON_SECRET" \
    https://web-production-1a800.up.railway.app/internal/reminders/dispatch \
    >> /var/log/ewash-reminders.log 2>&1
```

If Railway Cron Service is enabled, configure a Job pointing at the same URL
with the same header. The endpoint is idempotent — overlapping calls are
benign.

## Monitoring

```bash
# All dispatch outcomes
grep "reminders.dispatch"

# Just failures
grep "reminders.dispatch failed"

# Just successes
grep "reminders.dispatch sent"
```

Each successful or failed send emits one structured log line carrying
`reminder_id`, `ref`, `kind`, `attempt/max`, `duration_ms`, and (on failure)
the error class + message.

## Common failures

### 403 on the endpoint

- The cron job is missing the `X-Internal-Cron-Secret` header.
- Verify the value matches `INTERNAL_CRON_SECRET` in Railway variables.

### 503 on the endpoint

- `INTERNAL_CRON_SECRET` is unset in Railway. Set it and redeploy.

### `failed` rows accumulating

- Open `/admin/reminders` and confirm the active rule's `template_name` matches
  an approved Meta template in the correct language.
- Inspect the `error` column on the latest failed row — Meta send errors include
  the underlying `httpx` status (e.g. `HTTPStatusError: 400` on template-name
  mismatch, `... 401` on stale `META_ACCESS_TOKEN`).
- After fixing the root cause, the next cron tick re-attempts every row whose
  `attempt_count < max_sends`.

### Reminders queued but never sent

- Check that the booking is `status='confirmed'` (not still
  `pending_ewash_confirmation`). Reminders are only dispatched for confirmed
  rows; staff still needs to click **Confirmer eWash** in `/admin/bookings`.
- Check `scheduled_for` — H-2 means two hours before `appointment_start_at`,
  so a 9am booking has `scheduled_for` at 7am.

## Related

- Bead `ewash-b8w` — original spec.
- `app/persistence.py::confirm_booking_by_ewash` — where the rows are written.
- `app/notifications.py::notify_booking_confirmation` — staff alert path that
  this module mirrors but at a different lifecycle stage.
- `AGENTS.md` — FastAPI + asyncio rule (no celery/rq/dramatiq) and the
  two-step staff confirmation product invariant.
