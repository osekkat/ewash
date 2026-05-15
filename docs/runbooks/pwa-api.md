# Runbook: PWA API failures

Operational reference for staff and developers debugging issues on the `/api/v1/*` surface in production. Use the log-filter recipes at the end to triage faster.

## Quick triage

1. Open Railway → service `web` → **Logs** tab.
2. Filter by `ewash.api` to scope to the PWA API surface (excludes the WhatsApp webhook).
3. If the customer reported a timestamp, jump to it. Otherwise pull the last 5 minutes.
4. Match the failure shape below.

---

## 401 on `GET /api/v1/bookings` (Bookings tab won't load)

**Customer impact:** Bookings tab shows the empty "Aucune réservation" state even though the customer has booked.

**Diagnosis:**

1. Have the customer open the PWA → DevTools → Application → Local Storage and check `ewash.bookings_token` exists.
2. **Missing token:** they cleared site data, or the booking that minted it never finished. They need to make a fresh booking to mint a new token.
3. **Token present but the API still 401s:** the token was revoked (admin pass or `POST /api/v1/tokens/revoke`) or DB row was hand-deleted. Search Railway logs for `bookings.list invalid_token` near the failure time.

**Fix:**

- If token missing → tell the customer to make a fresh booking; the next response mints a new token automatically.
- If token revoked deliberately → expected behaviour, no fix.
- If invalid for unknown reasons → instruct the customer to clear localStorage (Settings → Site Data → Clear). Next booking issues a fresh token.

**Compensating control:** the customer can always see their bookings via the WhatsApp bot ("Mes réservations" intent). The PWA loss-of-history is recoverable, the data is not.

---

## 429 on `POST /api/v1/bookings` (rate limited)

**Customer impact:** booking submit fails with "Trop de tentatives, réessayez plus tard".

**Trigger thresholds (slowapi defaults from `app/config.py`):**

- 5 bookings per hour per phone
- 20 bookings per hour per IP

**Diagnosis:**

1. Search Railway logs for `bookings.create rate_limit_exceeded` near the timestamp.
2. Inspect the offending key (phone or IP).
3. Classify:
   - **Legitimate customer** (e.g., booking for a fleet of cars). Bump `RATE_LIMIT_BOOKINGS_PER_PHONE` temporarily.
   - **Abuse / scripted submission.** Leave the limit and tighten if needed.
   - **PWA bug causing a tight resubmit loop.** Check `mobile-app/booking.jsx` for missing `disabled` on the submit button after the first request. Roll back the offending deploy or hotfix.

**Fix:**

- Adjust `RATE_LIMIT_BOOKINGS_PER_PHONE` / `RATE_LIMIT_BOOKINGS_PER_IP` on Railway's env tab; service redeploys automatically.
- For abuse: the offending phone/IP appears in logs; document it for follow-up but do not unilaterally block at this layer (no IP allowlist in v1).

---

## 5xx on `POST /api/v1/bookings`

**Customer impact:** booking fails with the generic "Réservation impossible" message; the customer is told to retry.

**Diagnosis:**

1. Pull Railway logs around the timestamp. A 5xx always emits a full traceback.
2. Match the traceback to one of:
   - **`OperationalError` from psycopg / SQLAlchemy:** Postgres connection issue. Check Railway → Postgres → Metrics for CPU/connection saturation.
   - **`ValidationError` from Pydantic:** the PWA sent a payload shape the server doesn't accept. Usually means the PWA deployed before the server-side schema was merged; verify the order of recent deploys.
   - **Unexpected `Exception`:** an unhandled bug in the request handler. Cross-reference the file/line in the traceback.

**Mitigation:**

- **Operational stall (DB down, Meta API down):** wait it out. The customer can retry; the `client_request_id` idempotency guard prevents double-charges on resubmit.
- **Code bug:** the cleanest rollback is `EWASH_API_ENABLED=false` on Railway. The router unmounts; PWA Bookings tab falls back to the no-token empty state; WhatsApp bot is unaffected (different surface).
- **Postgres saturation:** scale up the Railway Postgres tier; the migration 0006 indexes are already optimised for the bookings-list and bookings-by-phone queries (see `br-ewash-6pa.1.2`).

---

## CORS errors (PWA can't reach API)

**Customer impact:** nothing loads on the PWA; DevTools shows `Access to fetch at ... has been blocked by CORS policy`.

**Diagnosis:**

1. Identify the origin reported in the DevTools error.
2. Compare against `ALLOWED_ORIGINS` (comma-separated exact list) and `ALLOWED_ORIGIN_REGEX` on Railway.
3. For Vercel preview branches: the regex must match `https://ewash-mobile-app-*.vercel.app` (or whatever the project's preview naming is).
4. A common foot-gun: a stale Vercel project rename leaves `prodDefault` in `mobile-app/config.js` pointing to the wrong Railway domain. Compare against the latest Railway domain.

**Fix:**

- Add the origin to `ALLOWED_ORIGINS` (single env var, comma-separated) or update `ALLOWED_ORIGIN_REGEX` and redeploy. CORS settles within ~30s after the deploy completes.
- Verify by running `OPTIONS` from a curl shell with `-H "Origin: <origin>"` and checking the `Access-Control-Allow-Origin` response header.

**Compensating control:** when both env vars are empty AND `EWASH_API_ENABLED=true`, the server logs a `WARNING: CORS is not configured` at startup. Grep for it.

---

## Staff WhatsApp alert not received

**Customer impact:** none directly; staff misses a booking and fails to confirm it within SLA. The booking is still in DB.

**Diagnosis:**

1. Confirm the booking row exists via `/admin/bookings`.
2. Search Railway logs for the booking ref + `notifications.staff_alert`. Two outcomes:
   - `notifications.staff_alert sent` → Meta accepted the template send. Staff phone may be offline / WhatsApp app uninstalled. Out of our control.
   - `notifications.staff_alert failed` → Meta returned an error. Common causes: stale `META_ACCESS_TOKEN`, template not approved in the current language, template name typo in `/admin/notifications`.

**Fix:**

- Re-check the template config in `/admin/notifications` (name, language, staff phone digits-only).
- If the access token expired, mint a fresh System User token (never-expires) and update `META_ACCESS_TOKEN`.
- If Meta is down: the booking IS still committed; the alert is best-effort. Manually walk the operator over to `/admin/bookings` and click Confirmer eWash.

---

## Stale prices in PWA after admin edit

**Customer impact:** PWA shows old prices for a service the admin just discounted.

**Diagnosis:**

1. The service worker (`mobile-app/service-worker.js`) caches `/api/v1/bootstrap`. A successful admin edit invalidates the server-side ETag, but a misbehaving SW can still serve the old cached response.
2. Check that `mobile-app/service-worker.js` early-returns on `path.startsWith('/api/')` so API calls bypass the cache entirely (planned in `br-ewash-6pa.6.12`).
3. Verify the bootstrap ETag is changing: `curl -I https://<railway>/api/v1/bootstrap` should return a new `ETag` after the admin edit.

**Fix:**

- If the SW has a `/api/*` carve-out: invalidate the customer's SW by bumping the cache version. The cache version is a constant in `service-worker.js`.
- If the SW does NOT have a `/api/*` carve-out: that's a regression. Patch the file to add the early-return, deploy Vercel.

---

## Quick log filters (Railway)

```bash
# All PWA API traffic
grep "ewash.api"

# Just the booking writes
grep "ewash.api" | grep "bookings.create"

# Rate-limit events
grep "rate_limit_exceeded"

# CORS warnings
grep "CORS is not configured"

# Staff alert outcomes
grep "notifications.staff_alert"

# Migration 0006 verification (one-off)
grep "alembic.runtime.migration" | grep "20260514_0006"
```

---

## Related docs

- `docs/adr/0001-token-scoped-pwa-reads.md` — why the read path uses opaque tokens instead of phone-keyed lookups.
- `AGENTS.md` — full set of product invariants and the two-step staff confirmation rule.
- `plan.md` — milestone plan; see `br ready` for the live status of any in-flight beads referenced above.
