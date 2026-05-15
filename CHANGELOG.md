# Changelog

All notable changes to Ewash are documented in this file. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version label is the string `app/main.py` returns from `/health`
(currently `v0.3.0-alpha17`). Releases are alpha until the PWA-backend
integration milestone closes and a production cutover is announced.

## [Unreleased]

Nothing yet. The next release will batch the remaining `[NEEDS-HUMAN]` and
`[BLOCKED-BY-DEP]` items from `docs/release-checklists/pwa-integration.md`.

## [0.3.0-alpha17] — 2026-05-15

### Added

- `/api/v1/*` router gated behind `EWASH_API_ENABLED` (see `app/api.py`,
  `app/main.py:108-115`) covering:
  - `GET /api/v1/bootstrap` — catalog + categories + slots + closed dates in
    one round-trip, with ETag-based caching.
  - `GET /api/v1/catalog/{services,categories,centers,closed-dates,time-slots}`
    — fine-grained read endpoints (Africa/Casablanca freshness filter on
    `time-slots`).
  - `POST /api/v1/promos/validate` — server-side promo validation with the
    catalog as source of truth.
  - `POST /api/v1/bookings` — creates `pending_ewash_confirmation` rows with
    `source="api"`, mints a `bookings_token`, schedules the staff alert via
    FastAPI `BackgroundTasks`, supports idempotent replay via
    `client_request_id`.
  - `GET /api/v1/bookings` — token-scoped read (header only, `?phone=` is
    explicitly rejected with 400 `phone_param_not_accepted`), cursor
    paginated.
  - `POST /api/v1/tokens/revoke` — logout (scope `current`) and rotation
    (scope `all`, mints a fresh token in the response so the calling device
    stays logged in).
  - `DELETE /api/v1/me` — customer self-serve data erasure under
    Loi 09-08 / GDPR, gated on the literal confirm phrase
    `I confirm I want to delete my data` enforced by a Pydantic `Literal`.
- Database migration `20260514_0006_pwa_integration.py`:
  - `bookings.client_request_id` + Postgres partial unique index for
    idempotent replay.
  - `bookings.source` (`whatsapp` | `api` | `admin`) + CHECK constraint +
    `ix_bookings_source` for dashboard split counters.
  - `customer_tokens` table (SHA-256 hashed at rest, plaintext returned
    exactly once in the booking response).
  - `data_erasure_audit` table (phone_hash + actor + counts, append-only).
  - Composite `ix_bookings_customer_phone_created_at` for the customer
    booking-list query.
  - `ON UPDATE CASCADE` on `bookings.customer_phone` FK so erasure's
    customer-rename is atomic on Postgres.
- Source-tracked bookings: admin dashboard split counters
  (`bookings_pwa_last_7d`, `bookings_whatsapp_last_7d`,
  `bookings_admin_last_7d`) and per-row source badges
  (`src-wa` / `src-pwa` / `src-admin`) in `/admin/bookings` and the
  dashboard recent-bookings card.
- Admin customer erasure tooling (`POST /admin/customers/{phone}/erase`,
  `GET /admin/erasures` review surface).
- Structured API access logs with `phone_hash` (SHA-256 prefix), never raw
  phone (`app/main.py:42-75`, `ApiAccessLogMiddleware`).
- Rate-limit primitives shared across the API: per-phone caps on bookings,
  per-IP umbrella, per-token caps on revoke / `/me`; defaults configurable
  via env vars (`RATE_LIMIT_*`, see `.env.example`).
- PWA delivery work:
  - Wire `mobile-app/api.js` to the new endpoints (bootstrap, promo
    validate, submit booking, fetch bookings, revoke token, delete account,
    add-to-calendar).
  - Hydrate the booking flow from `/api/v1/bootstrap` instead of the old
    hardcoded constants.
  - Add a Bookings tab fed by `GET /api/v1/bookings` with a detail modal
    (Add to Calendar `.ics` download, Book Again, Share via WhatsApp,
    Contact support).
  - Profile screen: Se déconnecter calls `tokens/revoke` before clearing
    `localStorage`; Supprimer mon compte forces the literal confirm phrase
    before activating the delete button.
  - Top-bar Help icon with current-screen identifier deep-links into
    WhatsApp.
  - Booking flow: draft autosave to `localStorage` with a 1h TTL and a
    Reprendre/Recommencer banner, error-recovery UX with a WhatsApp
    fallback CTA on 2 consecutive 5xx / 3 timeouts / offline state.
  - Structured debug logging (`?debug=1`) so operators can copy a run from
    a real device.
  - Service worker version-tagged cache name + `/api/*` cache bypass so
    catalog edits propagate without an SW unregister.
- End-to-end smoke test scripts under `tests/e2e/`:
  - `test_full_booking_flow.py` (full PWA booking → admin parity).
  - `test_token_lifecycle.py` (mint, reuse, fresh-mint-on-mismatch).
  - `test_pwa_bootstrap_etag.py` (cache headers, ETag round-trip).
  - `test_rate_limit_burst.py` (per-phone cap + Retry-After).
  - `test_cross_channel_dedup.py` (PWA + WhatsApp dedupe to the same
    customer).
  - `test_data_erasure.py` (DELETE /api/v1/me lifecycle smoke).
- Documentation:
  - `docs/adr/0001-token-scoped-pwa-reads.md` — opaque-token architecture
    rationale.
  - `docs/runbooks/pwa-api.md` — ops runbook for staging, prod migrate,
    rollback, and API-failure triage.
  - `docs/release-checklists/pwa-integration.md` — the pre-merge audit
    checklist (this release closed the three `[FAILED]` rows that 8.13
    flagged).
  - `docs/compliance/loi-09-08-data-erasure.md` — Moroccan data-protection
    retention policy, per-table erasure behaviour, operator runbook.
  - This file (`CHANGELOG.md`).

### Changed

- `README.md` rewritten to reflect the dual-runtime architecture (FastAPI
  backend on Railway + zero-build PWA on Vercel) and the production
  `web-production-1a800.up.railway.app` URL.
- `mobile-app/config.js` points at the live Railway API by default.
- `mobile-app/api.js` retries idempotent GETs (`_fetchWithRetry`).
- PWA prices now flow from the API bootstrap. Every hardcoded
  `CATEGORIES`, `SERVICE_OPTIONS`, `MOTO_SERVICES`, `ADDONS`,
  `CENTERS`, `VALID_PROMOS` constant in `mobile-app/booking.jsx` is gone;
  the file carries no prices of its own.
- Tariff screens in `mobile-app/screens.jsx` are sourced from the API
  catalog rather than the old hardcoded `TARIFF_*` arrays.
- Bot-side: `assign_booking_ref` no longer races on the first row of the
  year; `BookingRefCounterRow` is allocated under `with_for_update`.
- Booking confirmation logging strips plaintext phone + full payload —
  only `phone_hash` lands in the structured log line.
- Status FSM: a `pending_ewash_confirmation` booking cannot be rescheduled
  directly; staff must confirm first.
- Erasure helper purges `conversation_events` (FK-chained from
  `conversation_sessions`) and allows a repeat anonymization for a phone
  that booked again after a prior erasure.

### Fixed

- Idempotent `POST /api/v1/bookings` replay now verifies that the caller's
  phone matches the stored token before returning a booking response
  (closes the session-takeover bug from review round 1).
- Idempotent replay echoes the original `bookings_token` instead of
  minting a fresh one.
- 429 envelope shape is consistent between per-IP and per-phone caps
  (`Retry-After` header always present, JSON body identical).
- API booking rollback no longer leaves an in-memory `_bookings` shadow
  row when the DB write fails.
- Admin erasure audit actor is derived from the session timestamp + client
  host (rather than a generic `admin` string); notes are capped at 500
  characters.
- PWA service: catalog edits made in `/admin` are visible in the PWA
  without an SW unregister (the SW now bypasses cache entirely for
  `/api/*`).

### Removed

- Debug `GET /bookings` endpoint that previously leaked the in-memory
  booking list with no auth; the route now returns 404.

### Security

- Phone enumeration is mechanically impossible: `GET /api/v1/bookings`
  accepts `X-Ewash-Token` only; passing `?phone=…` returns 400
  `phone_param_not_accepted` instead of being silently ignored.
- `customer_tokens` and `data_erasure_audit` store SHA-256 hashes only — a
  DB dump never yields the raw phone or the raw token.
- The `bookings_token` plaintext is returned exactly once in the booking
  response; subsequent retrievals require holding the token client-side.
- Loi 09-08 / GDPR right-to-erasure surface: `DELETE /api/v1/me` (customer
  self-serve) and `POST /admin/customers/{phone}/erase` (admin) both call
  the same `anonymize_customer` helper, both write to
  `data_erasure_audit`, neither stores PII in the audit row.
- API access logs never emit plaintext phone or IP — only the SHA-256 hex
  prefix.

---

## [0.2.x and earlier]

Historical changes prior to the PWA-backend integration are not catalogued
here. See `git log` for the pre-`v0.3.0-alpha17` history (operational
schema migrations 0001-0005, the WhatsApp booking flow, the multi-page
admin portal, the Bouskoura location handling).

Earlier alphas in the `v0.3.0-alpha1` … `v0.3.0-alpha16` chain shipped
piecemeal as the PWA-backend integration plan (`plan.md`) was implemented;
this file consolidates all of that work under the cutover-ready release.
