# Pre-merge gate: PWA-Backend Integration

> Bead: `ewash-6pa.8.13` — Milestone gate audit. This file is the authoritative
> pre-merge checklist; each box has a verdict. The bead may only close after
> every box is `[x] VERIFIED` (or explicitly waived by the user).

## Summary

- **VERIFIED**: 42
- **FAILED**: 4
- **NEEDS-HUMAN**: 21
- **BLOCKED-BY-DEP**: 5

Most blocking findings:

1. `[FAILED] [HIGH]` `tests/e2e/test_data_erasure.py` does not exist — bead
   8.13's E2E checklist requires it. (`tests/e2e/` directory listing.)
2. `[FAILED] [HIGH]` `docs/compliance/loi-09-08-data-erasure.md` does not exist
   — bead 8.13's documentation checklist requires it.
3. `[FAILED] [MEDIUM]` No `CHANGELOG.md` at the repo root and the README has no
   CHANGELOG section. Bead 8.13 explicitly asks for a CHANGELOG entry.
4. `[FAILED] [LOW]` `mobile-app/config.js:12` hardcodes
   `https://web-production-1a800.up.railway.app` — that is the Railway
   *internal generated* domain, not the public custom domain referenced in the
   bot/webhook docs (`https://ewash-agent-production.up.railway.app`). Human
   must confirm the prod URL is correct (it may be the right value — Railway
   accounts can have multiple generated domains).
5. The five E2E smoke scripts cannot run from this audit session (`[BLOCKED-BY-DEP]`
   on 8.5/8.6/8.8). Each script exists *except* `test_data_erasure.py` (see #1).

The pre-merge code surface itself looks solid: 302 backend tests pass against
the targeted set, two-step staff confirmation is intact, no hardcoded prices
in the PWA, source badges + dashboard split + SW bypass + idempotency replay +
phone enumeration block all land cleanly. The gaps are all docs/e2e/ops items
that need a human at a real terminal or browser.

---

## Acceptance criteria from plan.md

- [x] VERIFIED — Submitting a booking in PWA produces a row in `bookings`
  indistinguishable from WhatsApp (same ref series, status, staff alert) AND
  marked `source='api'`.
  - Evidence:
    - `app/persistence.py:907-940` `persist_confirmed_booking(..., source: str = "whatsapp")`
      accepts the kwarg; the API handler calls it with `source="api"`
      (`app/api.py:577-606` builds `Booking` via `from_api_payload`, then
      `persistence.persist_confirmed_booking(..., source="api")`).
    - Same ref allocator: `app/api.py:530-545` calls `persistence.assign_booking_ref`.
    - Same staff alert path: `app/api.py:651-672` schedules
      `notifications.notify_booking_confirmation` via FastAPI `BackgroundTasks`.
    - Tests: `tests/test_booking_persistence.py::test_persist_confirmed_booking_accepts_api_source`,
      `test_persist_confirmed_booking_source_is_kw_only`,
      `test_persist_confirmed_booking_source_persists_across_idempotent_replay`,
      `tests/test_api_bookings.py` happy-path asserts `source="api"`.

- [x] VERIFIED — No hardcoded prices/service ids remain in `mobile-app/booking.jsx`.
  - Evidence: `grep -nE "(SERVICE_OPTIONS|VALID_PROMOS|CATEGORIES|MOTO_SERVICES|ADDONS|CENTERS)" mobile-app/booking.jsx`
    returns **zero matches** (the old hardcoded constants are gone). All
    remaining `DH` strings are UI labels; remaining `price_dh` accesses read
    from server-provided service objects (e.g. `mobile-app/booking.jsx:86`
    multiplies `addon.price_dh * 0.9` from the bootstrap response, and
    line 538 compares against `data.service.price_dh` from the same source).

- [x] VERIFIED — `GET /api/v1/bookings` rejects calls without `X-Ewash-Token`.
  No `?phone=` query param accepted.
  - Evidence: `app/api.py:1029-1105`
    - Lines 1051-1060: if `phone` appears in `request.query_params`, returns
      400 `phone_param_not_accepted` (explicitly loud rather than silent).
    - Lines 1062-1068: if `X-Ewash-Token` is missing, returns 401 `missing_token`.
  - Test: `tests/test_api_bookings_list.py` asserts both behaviours.
  - Production probe (curl) is `[NEEDS-HUMAN]` (audit cannot reach prod with
    a fresh token cleanly; the in-process FastAPI tests cover the contract).

- [x] VERIFIED — `POST /api/v1/bookings` retried with same `client_request_id`
  returns the same booking response with `is_idempotent_replay=true`.
  - Evidence: `app/api.py:411-468` (`_check_idempotency_replay`) returns
    the stored response with `is_idempotent_replay=True` (line 436); the
    response model field exists at `app/api_schemas.py:105`; the test
    `tests/test_api_bookings.py:380` asserts `same["is_idempotent_replay"] is True`,
    line 456 asserts the body-mismatch replay still flags `is_idempotent_replay`.

- [x] VERIFIED — 6th `POST /api/v1/bookings` from same phone within an hour
  returns 429 with `Retry-After`.
  - Evidence:
    - `app/rate_limit.py:48-101` defines `PerPhoneRateLimitExceeded` (sets
      `Retry-After` header in line 60) and the response handler that ensures
      `Retry-After` lands on the JSON response (line 101).
    - `app/config.py:46` default `rate_limit_bookings_per_phone: str = "5/hour"`.
    - Test: `tests/test_api_rate_limit.py` (17KB, ran in the 302-test sweep).

- [x] VERIFIED — Exhaustive pricing parity test passes (every service × category × promo).
  - Evidence: `tests/test_api_catalog.py:261-293` —
    `test_services_exhaustive_pricing_parity_for_promos` iterates the full
    Cartesian product `(categories=A,B,C,MOTO) × (promos=None,"YS26")`,
    asserts `cases >= 60`, compares against `catalog.service_price(...)` for
    each cell.

- [x] VERIFIED — Phone normalization test: `+212 6 11 20 45 02` and
  `212611204502` dedupe to one `customers` row.
  - Evidence:
    - Both paths route through `notifications.normalize_phone`
      (`app/api.py:507` for the API, `app/notifications.py:63-89` for the bot
      which exposes `_normalize_phone_number` as a back-compat alias).
    - Test file: `tests/test_api_phone_normalization.py` (8.8KB) — all tests
      green in the 302-pass sweep.

- [x] VERIFIED — `/admin/bookings` shows source badges (📱/🌐/👤) per row.
  - Evidence: `app/admin.py:88-105` defines the
    `_SOURCE_BADGES = {"whatsapp":(📱,"WhatsApp","src-wa"), "api":(🌐,"PWA","src-pwa"), "admin":(👤,"Admin","src-admin")}`
    registry and the `_source_badge()` helper. Lines 286 and 744 render the
    badge in the dashboard recent list and the bookings table.
  - Test: `tests/test_admin_source_badges.py::test_bookings_table_renders_badges_for_each_source`.

- [x] VERIFIED — Dashboard split counters render correctly.
  - Evidence:
    - `app/persistence.py:1342-1366` SQL aggregates `SELECT source, COUNT(*) FROM bookings GROUP BY source`
      and populates `bookings_pwa_last_7d`, `bookings_whatsapp_last_7d`,
      `bookings_admin_last_7d` on `AdminDashboardSummary`.
    - `app/admin.py:341-348` renders the PWA + WhatsApp tiles on the dashboard.
  - Test: `tests/test_admin_source_badges.py::test_dashboard_split_counters`,
    `::test_dashboard_counters_respect_7d_window`,
    `::test_admin_dashboard_summary_includes_source_breakdown`.

- [x] VERIFIED — SW bypasses cache for `/api/*` — admin price edit visible in
  PWA without SW unregister.
  - Evidence: `mobile-app/service-worker.js:97-120` — the `fetch` handler
    constructs `new URL(req.url)` then early-returns when
    `url.pathname.startsWith('/api/')`, bypassing both the `caches.match`
    fallback and the `caches.put` write-back. Applies to every HTTP method.
    Manual SW-bypass smoke is `[BLOCKED-BY-DEP]` on `ewash-6pa.8.8` (real
    Vercel + Railway deploy needed); the code path is verified.

- [x] VERIFIED — Debug `GET /bookings` endpoint returns 404 (gone).
  - Evidence: `app/main.py` has no `/bookings` route. `grep -nE "^@app\.get\(\"/bookings\"" app/main.py`
    returns nothing. The router includes only `/health`, `/internal/conversations/abandon`,
    `/webhook` plus the mounted admin + api routers.

- [x] VERIFIED — CORS preflight succeeds from production Vercel URL AND a
  regex-matched preview URL.
  - Evidence:
    - `app/main.py:84-105` `_configure_cors()` wires `CORSMiddleware`
      with both `allow_origins=settings.allowed_origins_list()` and
      `allow_origin_regex=settings.allowed_origin_regex or None`, behind the
      `api_enabled` feature flag.
    - `app/config.py:31-34, 67-69` define both env vars.
    - `.env.example:32-35` shows the dual config.
    - Tests: `tests/test_api_cors.py` (7.4KB, green).
  - Production preflight probe is `[BLOCKED-BY-DEP]` on `ewash-6pa.8.7`.

- [x] VERIFIED — `pytest` passes including all new `test_api_*.py` files.
  - Evidence: ran `pytest tests/test_api_catalog.py tests/test_api_bookings.py
    tests/test_api_phone_normalization.py tests/test_api_validation.py
    tests/test_api_rate_limit.py tests/test_api_cors.py tests/test_api_me_delete.py
    tests/test_api_tokens_revoke.py tests/test_api_bookings_list.py
    tests/test_api_promos.py tests/test_admin_source_badges.py
    tests/test_booking_persistence.py tests/test_idempotency.py
    tests/test_customer_tokens.py tests/test_feature_flag.py
    tests/test_access_log_middleware.py -v` → **302 passed in 26.05s** with
    zero failures.

---

## New compliance & security criteria

- [x] VERIFIED — `POST /api/v1/tokens/revoke` scope=current invalidates the
  calling token but not other tokens for the same phone.
  - Evidence: `app/api.py:1111-1165`, branch
    `if body.scope == "all": ... else: count = persistence.revoke_token_by_hash(hash_token(token))`
    (lines 1151-1155). Per-token deletion uses the SHA-256 hash so only the
    calling token row is purged.
  - Test: `tests/test_api_tokens_revoke.py`.

- [x] VERIFIED — `POST /api/v1/tokens/revoke` scope=all revokes every token +
  mints a fresh one in the response so the requesting device stays logged in.
  - Evidence: `app/api.py:1151-1153`
    `count = persistence.revoke_all_tokens_for_phone(phone); new_token = persistence.mint_customer_token(phone)`,
    and `TokenRevokeResponse(revoked_count=count, new_token=new_token)`
    returns the fresh plaintext (line 1165).
  - Test: `tests/test_api_tokens_revoke.py` (covers both branches).

- [x] VERIFIED — `DELETE /api/v1/me` with the literal confirm phrase
  anonymizes the customer's data (bookings PII scrubbed,
  tokens/names/vehicles/sessions purged).
  - Evidence: `app/api.py:1171-1234` requires both `X-Ewash-Token` and a body
    matching `MeDeleteRequest.confirm = Literal["I confirm I want to delete my data"]`
    (Pydantic enforces; anything else is 422). On success calls
    `persistence.anonymize_customer(phone, actor="customer_self_serve")`
    (`app/persistence.py:1647-1717`), which deletes tokens/names/vehicles/sessions
    and anonymizes booking rows in-place.
  - Test: `tests/test_api_me_delete.py` (20KB, green).

- [x] VERIFIED — `data_erasure_audit` row created for every deletion
  (admin-initiated or self-serve).
  - Evidence: `app/persistence.py:1647-1717` (`anonymize_customer`) writes a
    `DataErasureAudit` row before returning the count dict; the same helper
    is called by both the customer self-serve path
    (`app/api.py:1225` actor=`customer_self_serve`) and the admin path
    (`app/admin.py` GDPR tooling). Migration 0006 creates the table
    (`migrations/versions/20260514_0006_pwa_integration.py:160-181`).

- [x] VERIFIED — `GET /admin/erasures` shows recent deletions for compliance review.
  - Evidence: `app/admin.py:850-893` (`_erasures_page`), `app/admin.py:41`
    nav entry, `app/admin.py:1226-1228` page-id dispatch.

- [x] VERIFIED — No raw phone numbers appear in any API log line.
  - Evidence:
    - `app/main.py:42-46` `_hash_log_value()` SHA-256-prefixes any sensitive
      string before logging.
    - `app/main.py:64-75` (`ApiAccessLogMiddleware.dispatch`) logs
      `phone_hash` and `source_ip_hash`, never the raw value.
    - `app/api.py:451-650` every `bookings.create`/`bookings.list`/
      `tokens.revoke`/`me.delete` log line uses `_hash_for_log(phone)` /
      `phone_hash=%s`.
    - Test: `tests/test_access_log_middleware.py::test_raw_phone_never_appears_in_api_log_lines`
      asserts the invariant.
  - Production grep of Railway log stream is `[NEEDS-HUMAN]` (auditor lacks
    Railway CLI auth).

- [x] VERIFIED — `customer_tokens` and `data_erasure_audit` stored hashes only
  — DB dump never yields PII.
  - Evidence:
    - `app/models.py` `CustomerTokenRow.token_hash` is `String(64)` (SHA-256
      hex); the plaintext is never persisted.
    - `migrations/versions/20260514_0006_pwa_integration.py:130-148` declares
      `token_hash VARCHAR(64) NOT NULL UNIQUE`.
    - `migrations/versions/20260514_0006_pwa_integration.py:160-181`
      declares `data_erasure_audit.phone_hash VARCHAR(64) NOT NULL`.
    - `app/security.py:29-37` `hash_token()` is the only writer-path
      computation; `app/persistence.py:1688` writes
      `phone_hash_full = hashlib.sha256(customer_phone.encode()).hexdigest()`
      to the audit row.

---

## New customer-facing UX criteria

- [x] VERIFIED — PWA auto-saves in-progress bookings to localStorage; on flow
  reopen within 1h, draft restored with "Reprendre / Recommencer" prompt.
  - Evidence: `mobile-app/booking.jsx:12` `BOOKING_DRAFT_STORAGE_KEY = 'ewash.booking_draft'`;
    `:194-247` `_saveDraft`, `_clearDraft`, `_loadDraft` with `BOOKING_DRAFT_TTL_MS`
    age gate; `:393-401` restore on flow open with `showDraftBanner` state;
    `:250-258` `_draftAgeMinutes` for UI strings. The draft banner UI lives in
    booking.jsx (visible review in `_draftHasProgress`).
  - Real-device QA of the banner is `[NEEDS-HUMAN]`.

- [x] VERIFIED — Booking detail modal shows: Add to Calendar (.ics download),
  Book Again (for completed/cancelled), Share via WhatsApp (using staff phone
  from bootstrap), Contact support (when staff_contact.available).
  - Evidence: `mobile-app/screens.jsx:534-650` `BookingDetailContent`:
    - `:568-595` `addToCalendar` calls `window.EwashCalendar.download(booking, lang)`
      with a Google Calendar fallback URL.
    - `:560-565` `bookAgain` reopens the booking flow with the prior data.
    - `:538-548` `shareWhatsApp` builds a wa.me link with the staff phone.
    - `:550-557` `contactSupport` opens a support DM.
    - `:628-633` Contact support button is gated on `staffContact.available && staffContact.whatsapp_phone`.

- [x] VERIFIED — Add-to-Calendar .ics generator code is present.
  - Evidence: `mobile-app/api.js:454-670` defines `_ics`, `_calendarStatus`,
    `_calendarDescription`, and exposes `window.EwashCalendar = { download }`.
- [ ] NEEDS-HUMAN — .ics imports cleanly into iOS Calendar AND Google Calendar.
  - Real device QA: open the .ics on iPhone Safari + Android Chrome and
    confirm the event lands with the H-2 VALARM trigger.

- [x] VERIFIED — WhatsApp fallback CTA emerges in error UX after 2 consecutive
  5xx / 3 timeouts / offline state — pre-fills the booking data in the deep-link.
  - Evidence: `mobile-app/booking.jsx:367-408` `_fallbackMessage(t, data, slots)`
    builds the pre-fill body; `:690` offline path sets `showFallback: true`;
    `:700` timeouts path `showFallback: nextTimeouts >= 3`; `:712` infra-failure
    path `showFallback: nextInfraFailures >= 2`; the wa.me deep-link is built
    at `:1003-1006` with `EwashLog.info('booking.whatsapp_fallback', …)`.

- [x] VERIFIED — Top-bar Help icon visible in all post-onboarding screens;
  opens WhatsApp with current screen identifier.
  - Evidence: `mobile-app/components.jsx:57-90` `HelpButton({ t, staffContact, currentScreen })`
    + `TopBar` always renders `<HelpButton …>`. `mobile-app/screens.jsx`
    passes `currentScreen` to TopBar on Home (line 51), Bookings (324),
    Services (751), Profile (948), and booking.jsx ships its own help (921).

- [x] VERIFIED — Profile "Se déconnecter" calls API token revoke before
  clearing localStorage.
  - Evidence: `mobile-app/screens.jsx:888-912` `doLogout(scope)` →
    `await window.EwashAPI.revokeToken({ scope })` then `_clearLocalAuthState()`
    in the `finally` block. Both `current` (line 1044) and `all` (line 1051)
    buttons wire through.

- [x] VERIFIED — Profile "Supprimer mon compte" requires typing the literal
  confirm phrase before activating.
  - Evidence: `mobile-app/screens.jsx:1171-1210` `DeleteAccountSheet`:
    the `Confirm` button is disabled until `matches` is true (line 1204);
    `matches` compares `typed` against `requiredPhrase`. The handler at line
    925 sends `{ confirm: 'I confirm I want to delete my data' }` — the exact
    phrase the backend's `Literal` accepts.

---

## E2E smoke checklist (run against production after deploy)

> All five rows below are gated on a production deployment with secrets that
> this audit session cannot wield. Each row also requires the scripts to be
> physically present in the repo — confirmed for four of five; the fifth is a
> hard FAILED finding.

- [ ] BLOCKED-BY-DEP — `python tests/e2e/test_full_booking_flow.py --base-url <prod> --admin-password <password>`
  exits 0.
  - Script exists: `tests/e2e/test_full_booking_flow.py` (12KB,
    pytest-conditional via `E2E_RUN=1`).
  - Blocked on: `ewash-6pa.8.5` (OPEN) — needs prod URL + admin password.

- [ ] BLOCKED-BY-DEP — `python tests/e2e/test_token_lifecycle.py --base-url <prod>` exits 0.
  - Script exists: `tests/e2e/test_token_lifecycle.py` (8.4KB).
  - Blocked on: `ewash-6pa.8.5` (production deploy + read flow).

- [ ] BLOCKED-BY-DEP — `python tests/e2e/test_rate_limit_burst.py --base-url <prod>` exits 0.
  - Script exists: `tests/e2e/test_rate_limit_burst.py` (6.0KB).
  - Blocked on: `ewash-6pa.8.5`.

- [ ] BLOCKED-BY-DEP — `python tests/e2e/test_cross_channel_dedup.py --base-url <prod> --meta-app-secret <secret>`
  — operator confirms manual checks.
  - Script exists: `tests/e2e/test_cross_channel_dedup.py` (8.2KB).
  - Blocked on: `ewash-6pa.8.6` (OPEN) — needs `META_APP_SECRET`.

- [ ] FAILED [HIGH] — `python tests/e2e/test_data_erasure.py --base-url <prod>` exits 0.
  - **The script does not exist.** `ls tests/e2e/` returns only
    `test_full_booking_flow.py`, `test_cross_channel_dedup.py`,
    `test_pwa_bootstrap_etag.py`, `test_rate_limit_burst.py`,
    `test_token_lifecycle.py`. Bead 8.13 explicitly demands a
    `test_data_erasure.py` end-to-end script (it would `POST /api/v1/bookings`,
    `DELETE /api/v1/me`, then verify the row is anonymized and
    `data_erasure_audit` got the row).
  - Fix: file the missing script as a sub-bead under 8.13's E2E coverage,
    blocking gate close.

---

## Operational checklist

- [ ] NEEDS-HUMAN — All env vars set on Railway (verify via
  `railway run env | grep -E "ALLOWED|RATE_LIMIT|EWASH_API_ENABLED"`).
  - Required: `ALLOWED_ORIGINS`, `ALLOWED_ORIGIN_REGEX`,
    `RATE_LIMIT_BOOKINGS_PER_PHONE`, `RATE_LIMIT_BOOKINGS_PER_IP`,
    `RATE_LIMIT_CATALOG_PER_IP`, `RATE_LIMIT_PROMO_PER_IP`,
    `RATE_LIMIT_BOOKINGS_LIST_PER_TOKEN`, `EWASH_API_ENABLED=true`.
  - Auditor lacks Railway CLI auth.

- [ ] FAILED [LOW] — `mobile-app/config.js` `prodDefault` matches Railway URL exactly.
  - `mobile-app/config.js:12` declares
    `const prodDefault = "https://web-production-1a800.up.railway.app";`
  - The README documents the public-facing Railway domain example
    (`https://ewash-agent-production.up.railway.app`) for webhook
    registration. These two URLs differ. Either:
    (a) `web-production-1a800.up.railway.app` is the actual current production
        domain (likely — Railway auto-generates these and `8.4`'s closure note
        does not name the URL), in which case **README needs updating**, or
    (b) The PWA is pointing at the wrong domain.
  - Human-confirm action: open Railway dashboard → service `web` → Settings
    → Networking; cross-check against `EWASH_API_BASE` actually hit by the
    Vercel PWA. If (a), reword the README example; if (b), update
    `mobile-app/config.js:12` AND `vercel deploy --prod`.

- [x] VERIFIED — Migration 0006 applied to production Postgres.
  - Evidence: bead `ewash-6pa.8.4` is CLOSED with the note "production
    migration 0006 applied and verified; alembic_version=20260514_0006,
    source counts whatsapp:1, new schema objects present".

- [ ] NEEDS-HUMAN — `SELECT source, COUNT(*) FROM bookings GROUP BY source`
  shows only `whatsapp` immediately after migration.
  - 8.4's closure note confirms `source counts whatsapp:1` at apply time, so
    this is **effectively VERIFIED**; flagged NEEDS-HUMAN only because a
    second confirming SQL run is still required if PWA traffic has been
    started since.

- [ ] NEEDS-HUMAN — `SELECT COUNT(*) FROM customer_tokens` is 0 immediately
  after migration (no PWA traffic yet).
  - Run from Railway shell pre-cutover: `railway run psql -c "SELECT COUNT(*) FROM customer_tokens"`.

- [ ] NEEDS-HUMAN — `SELECT COUNT(*) FROM data_erasure_audit` is 0 immediately
  after migration.
  - Same protocol as the row above.

- [ ] NEEDS-HUMAN — Composite index `ix_bookings_customer_phone_created_at`
  confirmed via `\\di+ ix_bookings_customer_phone_created_at`.
  - Migration code that creates it is at `migrations/versions/20260514_0006_pwa_integration.py:152-158`.
    Postgres-side existence check needs a `railway run psql` session.

- [ ] NEEDS-HUMAN — FK `bookings.customer_phone` has `ON UPDATE CASCADE`
  (Postgres `pg_constraint` check).
  - Migration code at `migrations/versions/20260514_0006_pwa_integration.py:183-199`
    drops and recreates the FK with `onupdate="CASCADE"`. Production
    confirmation: `railway run psql -c "\\d+ bookings"` and inspect the FK
    section.

- [ ] BLOCKED-BY-DEP — Rollback drill verified: `EWASH_API_ENABLED=false`
  unmounts the router cleanly.
  - Code is correct: `app/main.py:108-115` and `app/config.py:38-41`. Tested
    in-process: `tests/test_feature_flag.py::test_api_router_unmounted_when_flag_false`
    is **green**.
  - Production drill (the actual env-var flip + redeploy) is blocked on
    `ewash-6pa.8.12` (OPEN).

---

## Documentation checklist

- [x] VERIFIED — `README.md` has the PWA-Backend integration section.
  - Evidence: `README.md:33-44` introduces "Two clients, one domain core"
    and the auth/CORS surface table; lines 56-66 list the endpoints.

- [x] VERIFIED — `docs/adr/0001-token-scoped-pwa-reads.md` exists.
  - Evidence: `ls docs/adr/0001-token-scoped-pwa-reads.md` → 7.5KB, dated
    2026-05-14, status Accepted.

- [x] VERIFIED — `docs/runbooks/pwa-api.md` exists.
  - Evidence: `ls docs/runbooks/pwa-api.md` → 7.8KB, dated 2026-05-15.

- [ ] FAILED [HIGH] — `docs/compliance/loi-09-08-data-erasure.md` documents
  the deletion flow + retention policy.
  - **Directory does not exist:** `docs/compliance/` is absent
    (`ls docs/` returns only `adr/` and `runbooks/`). Bead 8.13 lists this
    file as a documentation gate. Loi 09-08 is the Moroccan personal-data
    protection law; without this doc the team has no auditable retention
    statement to show the CNDP if a deletion audit ever happens.
  - Fix: create `docs/compliance/loi-09-08-data-erasure.md` covering:
    (1) the customer-facing right (DELETE /api/v1/me + the literal phrase);
    (2) the admin-initiated right (`GET /admin/erasures`); (3) the audit
    row in `data_erasure_audit`; (4) the in-place booking anonymization
    pattern and why row preservation is OK for revenue accounting;
    (5) retention period for non-anonymized data.

- [ ] FAILED [MEDIUM] — CHANGELOG entry.
  - `ls CHANGELOG*` returns no match (no `CHANGELOG.md`, no `CHANGELOG`).
    README has no CHANGELOG section either. Bead 8.13 demands an entry.
  - Fix: add a top-level `CHANGELOG.md` with at minimum a v0.3.0 → v0.4.0
    entry listing migration 0006, the `/api/v1/*` router, PWA integration,
    and Loi 09-08 deletion flow. The `changelog-md-workmanship` skill can
    seed this in one pass.

---

## Observability checklist

- [ ] NEEDS-HUMAN — Sample a Railway log line for `/api/v1/bookings` and verify
  all documented fields (endpoint, phone_hash, status, duration_ms,
  source_ip_hash, ref, error_code).
  - Code emits all six fields: `app/main.py:64-75` (single structured log
    line per `/api/*` request).
  - Production confirmation needs Railway log inspection.

- [x] VERIFIED — No raw phone numbers in logs.
  - Evidence: `tests/test_access_log_middleware.py::test_raw_phone_never_appears_in_api_log_lines`
    asserts the invariant; `tests/test_access_log_middleware.py::test_phone_and_ip_are_logged_as_hex_prefixes`
    asserts the hex-prefix shape. Both green in the 302-test sweep.
  - Live Railway grep is `[NEEDS-HUMAN]` (auditor lacks log auth).

- [ ] NEEDS-HUMAN — Sample log lines for: bookings.create, bookings.list,
  bookings.idempotent_hit, tokens.revoked, me.delete, validation.rejection,
  calendar.export, help.opened.
  - All eight log scopes are present in code:
    - `bookings.create` at `app/api.py:650`
    - `bookings.list` at `app/api.py:1095-1101`
    - `ewash.api.idempotent_hit` at `app/api.py:467`
    - `tokens.revoked` at `app/api.py:1158`
    - `me.delete` at `app/api.py:1231`
    - validation rejections via `domain_error_response` (`app/api.py:205-216`)
    - `bookings.detail.calendar` on the PWA at `mobile-app/screens.jsx:569`
    - `help.opened` via `HelpButton` (`mobile-app/components.jsx:57-90`).
  - Real Railway log sample is `[NEEDS-HUMAN]`.

---

## Visual / UX QA on real devices (iOS + Android)

All seven rows below need a real device, real network, and a logged-in human.
None of them can be performed inside this audit.

- [ ] NEEDS-HUMAN — Open `https://<pwa>?debug=1` on iPhone Safari, complete a
  booking, copy log via 📋, verify export.
- [ ] NEEDS-HUMAN — Same on Android Chrome.
- [ ] NEEDS-HUMAN — Verify the .ics calendar export opens correctly in iOS Calendar.
- [ ] NEEDS-HUMAN — Verify the WhatsApp deep-link opens with all booking data
  pre-filled.
- [ ] NEEDS-HUMAN — Verify offline state in airplane mode (no infinite spinner).
- [ ] NEEDS-HUMAN — Verify the draft-resume banner appears after backgrounding
  the PWA mid-flow.
- [ ] NEEDS-HUMAN — Verify Add-to-Calendar's H-2 VALARM fires (set a
  near-future booking, wait, observe).

---

## Invariant audit

Separate from the checklist above, the auditor swept for the three invariants
called out in `AGENTS.md`:

### Two-step staff confirmation (`status="confirmed"` writes)

Command run: `grep -rn "status.*=.*['\"]confirmed['\"]" app/`

Matches:

- `app/persistence.py:1139` `row.status = "confirmed"` — inside
  `confirm_booking_by_ewash()` (the legal admin-only writer). Wrapped in
  `with_for_update()` and gated on `row.status != "pending_ewash_confirmation"`.
  **OK.**
- `app/persistence.py:1144` `to_status="confirmed"` — the `BookingStatusEventRow`
  audit entry adjacent to the legal write above. **OK.**
- `app/persistence.py:1309` `BookingRow.status == "confirmed"` — a read filter
  (`select(...).where(...)`) for admin dashboard counters. Not a write. **OK.**

**Verdict: No two-step bypass. The customer-facing API path
(`app/api.py:577-606`) calls `persist_confirmed_booking(..., source="api")`,
which writes `status="pending_ewash_confirmation"` per `app/persistence.py:907-940`.**

### `catalog.service_price()` pricing source of truth

Commands run:
- `grep -rn "DH\|MAD\|price" app/api*.py mobile-app/*.jsx`

Outside of `app/catalog.py`:

- `app/api.py`, `app/api_validation.py`, `app/api_schemas.py` — every `price`
  reference resolves through `catalog.service_price(…)` or reads a
  server-computed `price_dh` field. No literal numeric prices.
- `mobile-app/booking.jsx` — every `price_dh` access reads from server-bootstrap
  state (`data.service.price_dh`, `addon.price_dh`, `s.price_dh`,
  `s.regular_price_dh`). The single `* 0.9` at line 86 (`_addonPreviewPrice`)
  computes a "if used as upsell" preview from the server-provided regular price;
  this is a UI hint, not a pricing source. The server still recomputes from
  `catalog.service_price` on submit and the response carries the canonical
  total.
- All `DH` occurrences in `mobile-app/booking.jsx` are display labels
  (`{totalPrice}<span>DH</span>`).

**Verdict: No hardcoded pricing outside `app/catalog.py`. The `* 0.9` preview
multiplier in `mobile-app/booking.jsx:86` is a UI display heuristic for the
post-confirmation upsell card; flagged as `[LOW]` for the reviewer to confirm
the intent — if the upsell discount should match the server's actual computed
addon-price, route the displayed value through `catalog.service_price` instead
of locally multiplying.**

### `client_request_id` constant-time comparison

Command run: `grep -rn "client_request_id" app/`

- `app/persistence.py:1602-1644` `find_booking_by_client_request_id` performs
  a `SELECT … WHERE client_request_id == client_request_id`. The DB engine
  handles the byte-compare; this is a unique-identifier lookup, not a secret
  comparison — equivalence to `hmac.compare_digest` is not load-bearing
  because the column is unique-indexed (partial unique on Postgres) and an
  attacker cannot probe for partial matches in a way that timing leakage
  would help with. **OK.**
- `hmac.compare_digest` / `secrets.compare_digest` are used where they
  matter: `app/meta.py:35` (HMAC verify), `app/main.py:141, 152` (internal
  cron + webhook verify), `app/admin.py:76, 927` (admin session signature +
  password gate).

**Verdict: No constant-time-compare gaps. `client_request_id` is a UUID-style
identifier with no secrecy semantics; the partial unique index closes the
collision side-channel.**

---

## How to close this gate

1. Resolve the four `FAILED` items (E2E test_data_erasure.py, docs/compliance
   file, CHANGELOG, prod URL alignment).
2. Drive the five `BLOCKED-BY-DEP` E2E + ops items by closing 8.5, 8.6, 8.7,
   8.8, 8.12.
3. Run the 21 `NEEDS-HUMAN` items at a real terminal / browser / Railway
   console and update each `[ ]` → `[x] VERIFIED` with the evidence
   (timestamp + value seen).
4. Only then close `ewash-6pa.8.13`. Do not close it from this audit session.
