# AGENTS.md — Ewash

> Guidelines for AI coding agents working in this Python + JSX codebase.

---

## RULE 0 - THE FUNDAMENTAL OVERRIDE PREROGATIVE

If I tell you to do something, even if it goes against what follows below, YOU MUST LISTEN TO ME. I AM IN CHARGE, NOT YOU.

---

## RULE NUMBER 1: NO FILE DELETION

**YOU ARE NEVER ALLOWED TO DELETE A FILE WITHOUT EXPRESS PERMISSION.** Even a new file that you yourself created, such as a test code file. You have a horrible track record of deleting critically important files or otherwise throwing away tons of expensive work. As a result, you have permanently lost any and all rights to determine that a file or folder should be deleted.

**YOU MUST ALWAYS ASK AND RECEIVE CLEAR, WRITTEN PERMISSION BEFORE EVER DELETING A FILE OR FOLDER OF ANY KIND.**

---

## Irreversible Git & Filesystem Actions — DO NOT EVER BREAK GLASS

1. **Absolutely forbidden commands:** `git reset --hard`, `git clean -fd`, `rm -rf`, or any command that can delete or overwrite code/data must never be run unless the user explicitly provides the exact command and states, in the same message, that they understand and want the irreversible consequences.
2. **No guessing:** If there is any uncertainty about what a command might delete or overwrite, stop immediately and ask the user for specific approval. "I think it's safe" is never acceptable.
3. **Safer alternatives first:** When cleanup or rollbacks are needed, request permission to use non-destructive options (`git status`, `git diff`, `git stash`, copying to backups) before ever considering a destructive command.
4. **Mandatory explicit plan:** Even after explicit user authorization, restate the command verbatim, list exactly what will be affected, and wait for a confirmation that your understanding is correct. Only then may you execute it—if anything remains ambiguous, refuse and escalate.
5. **Document the confirmation:** When running any approved destructive command, record (in the session notes / final response) the exact user text that authorized it, the command actually run, and the execution time. If that record is absent, the operation did not happen.

## Toolchain: Python & pip

We only use **pip + a virtualenv** for the backend, NEVER poetry/pipenv/uv/conda. The PWA is **zero-build** — no npm, no yarn, no bundler.

- **Python:** 3.12 (pinned in `runtime.txt`). Backend venv at `.venv/`.
- **Dependencies:** Pinned exact versions in `requirements.txt` (no ranges).
- **Migrations:** Alembic 1.14, scripts in `migrations/versions/`, config in `alembic.ini`.
- **Deploy:** Railway (Nixpacks) for `app/` via `Procfile` + `railway.toml`; Vercel for `mobile-app/` via `vercel.json`.
- **PWA runtime:** React 18.3.1 + ReactDOM + `@babel/standalone` 7.29.0 from unpkg CDN with SRI hashes. No bundler, no Node toolchain. Files self-register on `window` and load in order from `mobile-app/index.html`.

### Async Runtime: FastAPI + asyncio (MANDATORY — NO CELERY, NO RQ)

**This project uses FastAPI's native async/await and `BackgroundTasks` for deferred work. No external task queue exists.**

- **Inbound:** `POST /webhook` is async; `meta.verify_signature` is synchronous (HMAC).
- **Outbound:** `httpx.AsyncClient` for all Meta Cloud API calls (`app/meta.py`).
- **Deferred work:** when scheduling work that should not block the response (e.g., the planned staff notification path from the API), use FastAPI `BackgroundTasks`, NOT a thread pool, NOT a separate worker. The bot's webhook handler keeps notifications inline today so reply ordering is preserved — do not break that without weighing the trade-off.

**Forbidden additions**: `celery`, `rq`, `dramatiq`, `huey`, `apscheduler`, any external broker (Redis/RabbitMQ) added solely as a job queue. The reminder dispatcher is intentionally not yet built; when it lands it should be a thin cron-driven script or a single-process polling loop, not a new infra layer.

### Key Dependencies

| Package                 | Purpose                                                   |
| ----------------------- | --------------------------------------------------------- |
| `fastapi==0.115.5`      | HTTP framework (webhook + admin + future API)             |
| `uvicorn[standard]`     | ASGI server (used by `Procfile` and `railway.toml`)       |
| `httpx==0.27.2`         | Async HTTP client for Meta Cloud API calls                |
| `pydantic-settings`     | `app/config.py` — env-driven settings                     |
| `SQLAlchemy==2.0.36`    | ORM for all 22 tables in `app/models.py`                  |
| `alembic==1.14.0`       | DB migrations (`migrations/versions/0001`–`0005`)         |
| `psycopg[binary]`       | Postgres driver (prod). Tests use SQLite in-memory.       |
| `pytest==8.3.4`         | Test framework (`tests/`, 14 files, ~68 tests)            |
| `pytest-asyncio==1.3.0` | Async test support (`asyncio_default_fixture_loop_scope`) |

PWA has no `package.json` and no JS dependencies declared in this repo — everything is CDN-fetched at runtime.

### Deployment Profile

- **Backend on Railway**: Nixpacks builder, `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, health check on `/health`.
- **PWA on Vercel**: static files served with `vercel.json` cache headers — long-immutable on icons, short must-revalidate on JSX/JS/CSS, `no-store` on `service-worker.js`.
- **Version label**: `app/main.py` declares `v0.3.0-alpha17`. README still claims "v0.1 echo bot" — that is stale, leave the README alone unless explicitly asked.

### Documentation Invariants for Numeric Claims

If you add a "saves N litres of water" or "X bookings in Y days" claim to README, marketing copy, or the PWA shell, name the source of the number (admin dashboard query, Meta funnel export, hand-collected data) and the date. Do not borrow numbers from the PWA's `HomeScreen` mock counters (`2,147L`, `23 washes` in `mobile-app/screens.jsx`) — those are placeholder animations, not measurements. If the metric is unmeasured, say "estimated" or do not include the number.

---

## Code Editing Discipline

### No Script-Based Changes

**NEVER** run a script that processes/changes code files in this repo. Brittle regex-based transformations create far more problems than they solve.

- **Always make code changes manually**, even when there are many instances
- For many simple changes: use parallel subagents
- For subtle/complex changes: do them methodically yourself

### No File Proliferation

If you want to change something or add a feature, **revise existing code files in place**.

**NEVER** create variations like:

- `main_v2.py`
- `handlers_improved.py`
- `booking_enhanced.jsx`

New files are reserved for **genuinely new functionality** that makes zero sense to include in any existing file. The bar for creating new files is **incredibly high**.

The integration plan in `plan.md` explicitly calls for two new files (`app/api.py`, `mobile-app/api.js` and `mobile-app/config.js`) — those are the documented exceptions. Anything else should live inside an existing module.

---

## Backwards Compatibility

We do not care about backwards compatibility — Ewash is pre-launch with no production customers. We want to do things the **RIGHT** way with **NO TECH DEBT**.

- Never create "compatibility shims"
- Never create wrapper functions for deprecated APIs
- Just fix the code directly

The one nuance: the bot is **live with internal staff testing on a Meta test number**. Schema changes that break in-flight in-memory sessions are fine (sessions reset on every Railway redeploy by design — see `app/state.py`). DB schema changes must still ship as an Alembic migration; do not edit existing migrations in place — write a new one.

---

## Quality Gates (CRITICAL)

**After any substantive code changes, you MUST verify no errors were introduced:**

```bash
# Run the full backend test suite
pytest

# Run a single test file
pytest tests/test_booking_persistence.py

# Run a single test
pytest tests/test_ewash_confirmation_status.py::test_admin_confirmation_promotes_status

# Run with output
pytest -s

# Run with verbose names
pytest -v
```

If you see errors, **carefully understand and resolve each issue**. Read sufficient context to fix them the RIGHT way. Tests use SQLite in-memory; Postgres-specific behaviour (partial indexes, check constraints) is exercised only in production. If a planned migration relies on a Postgres-only feature, gate it behind a dialect check the way `migrations/versions/20260505_0003_*.py` does.

For the PWA there is no automated test suite. After any `mobile-app/*.jsx` change, **load `mobile-app/index.html` in a browser** and walk the relevant flow — there is no type checker to catch a stray `{undefined}` for you.

---

## Testing

### Testing Policy

Every backend module that ships a behaviour change must come with a test in `tests/`. Tests must cover:

- Happy path
- Edge cases (closed dates, slot freshness, moto-vs-car lane, returning customer)
- Error conditions (admin auth failures, idempotency on retry, DB absent)

The test suite **does not** use a Postgres fixture. SQLite in-memory is the default; production-only behaviour (`with_for_update`, `ON CONFLICT`, partial unique indexes) requires extra care when designing the test.

### Running Tests

```bash
# Activate venv first
source .venv/bin/activate

# Run all tests
pytest

# Run tests in a file
pytest tests/test_admin_routes.py

# Run tests matching a name
pytest -k "returning_customer"

# Show stdout
pytest -s
```

### Test Categories

| Test File                           | Focus Areas                                                                   |
| ----------------------------------- | ----------------------------------------------------------------------------- |
| `test_admin_routes.py`              | Admin portal auth, all GET pages, every POST upsert path, DB-absent fallback  |
| `test_booking_persistence.py`       | `persist_confirmed_booking`, customer/vehicle upsert, ref counter, line items |
| `test_returning_customer_flow.py`   | Returning-customer detection, name/vehicle recall, skip-step shortcuts        |
| `test_ewash_confirmation_status.py` | `pending_ewash_confirmation` → `confirmed`, H-2 reminder row creation         |
| `test_booking_notifications.py`     | Staff template parameter construction, settings normalization                 |
| `test_db_foundation.py`             | Schema creation, normalized model/color tables, full booking roundtrip        |
| `test_addon_recap.py`               | Detailing upsell recap message structure                                      |
| `test_catalog_baseline.py`          | `service_price`, YS26 promo, WhatsApp row text limits (≤24/≤72)               |
| `test_services_tariff_images.py`    | Tariff JPG image links, captions                                              |
| `test_models_status_reminders.py`   | 15-status FSM transitions, reminder rule scheduling math                      |
| `test_admin_i18n.py`                | fr/en lookups, locale normalization (default fr)                              |
| `test_health.py`                    | `/health` endpoint exposes version                                            |
| `test_config_defaults.py`           | Settings defaults: empty creds, 1-week session TTL                            |

### Test Patterns

- **No shared DB fixture**: each test calls `make_engine(":memory:")` and `init_db(engine)` directly. Some use `tmp_path` for file-backed SQLite.
- **Meta API mocking**: `conftest.py:7-10` plants placeholder env vars; individual tests monkeypatch `meta.send_text`, `meta.send_buttons`, `meta.send_list`, `meta.send_template`, `meta.send_image_link` with async fakes.
- **Async tests**: `@pytest.mark.asyncio` + `async def` for handler-level tests.
- **No property-based or snapshot testing yet.** If you reach for one, justify it; it would be the first.

### Coverage Gaps (Known)

- **Reminder dispatch**: rows are written but no worker sends them. No test exists for the missing worker.
- **Bot handler edge cases**: malformed button payloads, unknown row ids, mid-flow timeouts.
- **PWA**: no automated tests at all. Manual browser verification is the only check.

---

## Third-Party Library Usage

If you aren't 100% sure how to use a third-party library, **SEARCH ONLINE** to find the latest documentation and current best practices. SQLAlchemy 2.x and Pydantic v2 changed enough from their predecessors that old StackOverflow answers will quietly mislead you — verify against the current docs.

---

## Ewash — This Project

**This is the project you're working on.** Ewash is a pre-launch eco car-wash service in Bouskoura / Casablanca, Morocco. The customer channel is WhatsApp (Morocco-native). The repo packages the product as **two independent runtimes that don't talk to each other yet**:

- **`app/` (FastAPI backend, Railway)** — a French-language WhatsApp bot on Meta Cloud API v21.0, plus a multi-page admin portal at `/admin` (password-gated, fr+en). Version label `v0.3.0-alpha17`. Persists to Postgres via SQLAlchemy + Alembic. 22 tables, 5 migrations.
- **`mobile-app/` (React 18 PWA, Vercel)** — a high-fidelity zero-build prototype in French + Arabic with RTL support. **Does not call the backend.** The booking flow is a redraw of the bot's logic with hardcoded mock data. Recent commits are iterating on visual polish.

`plan.md` is the integration plan: a `/api/v1/*` router that lets the PWA become a second client of the same domain core (same `EW-YYYY-####` ref series, same `catalog.service_price`, same staff alert). **It is not implemented yet** — no `app/api.py`, no migration `0006`, no `mobile-app/api.js`.

### CRITICAL: The Two-Step Staff Confirmation Is Deliberate — DO NOT BYPASS

> **This is the single most important product invariant. Violating it commits Ewash to slots that staff has not vetted.**

When a customer confirms a booking on WhatsApp (or, post-integration, in the PWA), the booking is persisted with `status = "pending_ewash_confirmation"`. **Staff must then click "Confirmer eWash" in `/admin/bookings`** to promote the row to `status = "confirmed"`. Only then is the slot considered committed; only then does the H-2 reminder row get created. This is a product decision — staff verifies feasibility (location, vehicle, slot capacity) before committing.

**YOU MUST NEVER:**

1. **Have the customer-facing path write `status = "confirmed"` directly.** `persist_confirmed_booking()` in `app/persistence.py` writes `pending_ewash_confirmation` by design. The admin path `confirm_booking_by_ewash()` is the only function allowed to promote to `confirmed`.

2. **Add an auto-confirm timer, scheduled job, or "trust the customer" shortcut.** If a customer-confirmed booking sits in `pending_ewash_confirmation` for 24 hours, that is a staff process problem to surface in `/admin`, not an engineering problem to solve by auto-promoting.

3. **Allow an unauthenticated endpoint to promote a booking to `confirmed`.** `POST /admin/bookings/confirm` lives behind the admin session cookie; the planned `/api/v1/*` router for the PWA must NOT include a confirm endpoint. The PWA only creates `pending_ewash_confirmation` rows.

4. **Bypass `ALLOWED_STATUS_TRANSITIONS`** in `app/models.py`. The status FSM allows `pending_ewash_confirmation → confirmed → {rescheduled|technician_en_route|completed|cancelled|…}` and disallows skipping the pending step. `transition_booking_status()` enforces this — don't rewrite it to be permissive.

**The key locations you must never regress:**

- `app/persistence.py` → `persist_confirmed_booking()` writes `pending_ewash_confirmation`, never `confirmed`
- `app/persistence.py` → `confirm_booking_by_ewash()` is the only `confirmed` writer (uses `with_for_update`)
- `app/admin.py` → `POST /admin/bookings/confirm` is the only HTTP surface that calls it
- `app/models.py` → `ALLOWED_STATUS_TRANSITIONS` is the FSM source of truth
- `app/handlers.py` → the WhatsApp `BOOK_CONFIRM` branch must call `assign_booking_ref` + `persist_confirmed_booking` only, never anything that promotes to `confirmed`

**Why this rule exists:** Ewash is a physical service with finite slots and finite staff. A confirmation that has not been seen by a human is a commitment Ewash cannot keep. If you are unsure whether a change affects booking lifecycle, ASK before making it.

### Secondary Critical Invariant: `catalog.service_price()` Is the Pricing Source of Truth

There is exactly one pricing function: `catalog.service_price(service_id, category, promo_code=None)` in `app/catalog.py`. The WhatsApp bot uses it. The admin portal reads through it. The planned `/api/v1/*` router MUST use it. The PWA currently has hardcoded prices that diverge from the bot (the PWA shows a `-15%` promo where the bot applies `-10%`); the integration plan's acceptance criterion is that the PWA carries no prices of its own after wiring.

**Never** introduce a second pricing function, a hardcoded price table outside `app/catalog.py`, or a per-endpoint pricing override. If admins need a price they cannot reach today, add it to the catalog/DB-override path, not to a callsite.

### Architecture

```
                                                       (planned, not yet built)
Customer WhatsApp           POST /webhook             PWA (Vercel) ─POST /api/v1/bookings─┐
      │                          │                                                        │
      ▼                          ▼                                                        ▼
Meta Cloud API v21.0  ──▶ app/main.py ──▶ app/handlers.py (state machine, in-mem)   app/api.py
      ▲                                          │                                        │
      │                                          ▼                                        │
      └────────── meta.send_* ◀── app/booking.py (Booking dataclass) ◀──────────────────── │
                                                 │                                        │
                                                 ▼                                        │
                                          app/persistence.py ◀─────────────────────────────┘
                                                 │
                          ┌──────────────────────┼──────────────────────┐
                          ▼                      ▼                      ▼
                    Postgres (Railway)   app/catalog.py          app/notifications.py
                    22 tables / Alembic   (pricing source        (staff WhatsApp
                                            of truth)             template alert)
                                                                        │
                                                                        ▼
                                                                  Meta Cloud API
```

**Customer flow (WhatsApp, today):** Meta delivers the message → HMAC verified → state machine in `app/handlers.py` (in-memory session keyed by phone) drives a button/list conversation → on `BOOK_CONFIRM`, `assign_booking_ref` + `persist_confirmed_booking(status=pending_ewash_confirmation)` + `notify_booking_confirmation` → staff sees row in `/admin/bookings` → staff clicks Confirmer eWash → `confirm_booking_by_ewash` promotes to `confirmed` and writes the H-2 reminder row.

**Customer flow (PWA, planned):** PWA opens → `GET /api/v1/bootstrap` returns catalog + slots + closed dates in one round-trip → customer fills the same flow → `POST /api/v1/bookings` runs through the same `assign_booking_ref` + `persist_confirmed_booking(source="api")` + `BackgroundTask(notify_booking_confirmation)` path → response includes opaque `bookings_token` stored once in `localStorage`. The staff confirmation step is identical.

### Project Structure

```
ewash/
├── README.md                          # Stale — claims v0.1 echo bot. Don't believe it.
├── AGENTS.md                          # This file.
├── plan.md                            # PWA ↔ backend integration plan (not yet built).
├── requirements.txt                   # Backend Python deps (pinned).
├── runtime.txt                        # python-3.12
├── Procfile                           # uvicorn launch for Railway
├── railway.toml                       # Nixpacks + health check on /health
├── alembic.ini                        # Migration config
├── pytest.ini                         # pythonpath=., testpaths=tests
├── .env.example                       # Meta creds, DATABASE_URL, ADMIN_PASSWORD, etc.
├── app/                               # ─── FastAPI backend ───
│   ├── main.py                        # FastAPI app, /webhook, /health, /admin mount, /bookings debug (TO REMOVE)
│   ├── config.py                      # pydantic-settings — env-driven config
│   ├── meta.py                        # Meta Cloud API client — HMAC verify, send_text/buttons/list/template/image_link
│   ├── handlers.py                    # WhatsApp state machine (_DISPATCH table at line 897)
│   ├── state.py                       # In-memory session dict keyed by phone, 2h timeout
│   ├── booking.py                     # Booking dataclass + in-memory _bookings shadow list + ref counter
│   ├── catalog.py                     # Services, prices, promos, slots, centers, closed dates (static + DB overrides)
│   ├── persistence.py                 # All DB writes — assign_booking_ref, persist_confirmed_booking, confirm_booking_by_ewash, …
│   ├── models.py                      # 22 SQLAlchemy models + ALLOWED_STATUS_TRANSITIONS + status enum constants
│   ├── db.py                          # Engine init, session_scope, init_db, backfill helpers
│   ├── notifications.py               # Staff template alert (notify_booking_confirmation)
│   ├── admin.py                       # Multi-page admin portal — inline HTML, session cookie, all CRUD routes
│   ├── admin_i18n.py                  # fr/en strings (admin only — does not translate bot strings)
│   └── static/                        # Tariff JPGs served via /static
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 20260505_0001_operational_schema.py
│       ├── 20260505_0002_customer_contact_capture.py
│       ├── 20260505_0003_schema_constraints_and_indexes.py
│       ├── 20260505_0004_booking_notifications.py
│       └── 20260506_0005_customer_name_history.py
├── tests/                             # 14 files, ~68 tests, SQLite in-memory
├── mobile-app/                        # ─── Zero-build React PWA ───
│   ├── index.html                     # Loads React, ReactDOM, Babel-standalone, then JSX files in dep order
│   ├── app.jsx                        # Shell: splash → lang → app, tab routing, modal state
│   ├── booking.jsx                    # 11-step booking flow (HARDCODED catalog, faked ref)
│   ├── screens.jsx                    # Home / Bookings / Services / Profile / Support tabs (mock data)
│   ├── components.jsx                 # Shared UI kit, registers on window.*
│   ├── auth.jsx                       # Splash + language picker
│   ├── icons.jsx                      # SVG icon set
│   ├── i18n.js                        # FR + AR strings (183+ keys, RTL handling)
│   ├── tweaks-panel.jsx               # Dev/design control kit (variant/theme/language switching)
│   ├── service-worker.js              # Network-first, cache fallback (no /api/* carve-out yet)
│   ├── manifest.webmanifest           # standalone, theme #1FA9A9
│   ├── vercel.json                    # Cache headers, COOP/COEP, geolocation perm policy
│   ├── styles.css                     # CSS custom properties, dark/light, Eco/Premium variants
│   └── assets/                        # Icons, logos
└── .beads/                            # Beads issue tracker state (see Beads section below)
```

### Key Files by Module

| Module / File                  | Purpose                                                                                                                                                            |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `app/main.py`                  | FastAPI app, `POST /webhook` (HMAC verify, dispatch), `/health`, `/admin` mount                                                                                    |
| `app/config.py`                | `Settings` (pydantic-settings) — Meta creds, DB URL, admin auth, locale defaults                                                                                   |
| `app/meta.py`                  | `verify_signature` (HMAC-SHA256), `send_text/buttons/list/template/image_link`                                                                                     |
| `app/handlers.py`              | State machine — `_DISPATCH` table, escape hatches, returning-customer flow                                                                                         |
| `app/state.py`                 | `_sessions` dict (in-memory only — resets on redeploy), 2h stale cutoff                                                                                            |
| `app/booking.py`               | `Booking` dataclass, in-memory `_bookings` shadow, ref counter                                                                                                     |
| `app/catalog.py`               | `service_price` (THE pricing function), `VEHICLE_CATEGORIES`, `SERVICES_WASH/DETAILING/MOTO`, `PROMO_CODES`, `SLOTS`, `CENTERS`, `CLOSED_DATES`, all admin upserts |
| `app/persistence.py`           | `assign_booking_ref` (with*for_update), `persist_confirmed_booking`, `confirm_booking_by_ewash`, `persist_customer_name`, `admin*\*` dashboard queries             |
| `app/models.py`                | All 22 ORM models, `ALLOWED_STATUS_TRANSITIONS`, `transition_booking_status`, reminder rule generation                                                             |
| `app/db.py`                    | `make_engine`, `session_scope`, `init_db`                                                                                                                          |
| `app/notifications.py`         | `notify_booking_confirmation` — Meta template send to staff                                                                                                        |
| `app/admin.py`                 | Session cookie auth, dashboard, all CRUD pages, `POST /admin/bookings/confirm`                                                                                     |
| `app/admin_i18n.py`            | fr/en translation dict (admin only)                                                                                                                                |
| `mobile-app/app.jsx`           | PWA shell — splash, lang, tabs, modal, standalone detection                                                                                                        |
| `mobile-app/booking.jsx`       | 11-step flow, hardcoded `CATEGORIES`/`SERVICE_OPTIONS`/`MOTO_SERVICES`/`ADDONS`/`CENTERS`/`VALID_PROMOS`, fake ref at line 1010                                    |
| `mobile-app/screens.jsx`       | Home / Bookings / Services / Profile / Support, `TARIFF_LAVAGE` / `TARIFF_ESTHETIQUE`                                                                              |
| `mobile-app/i18n.js`           | FR/AR strings, day/month arrays, RTL handling                                                                                                                      |
| `mobile-app/service-worker.js` | Network-first, cache fallback. NO `/api/*` bypass yet (will be needed post-integration)                                                                            |

### Key Design Decisions

- **Two-step staff confirmation** is the deliberate booking lifecycle. See the CRITICAL section above. Customer confirm → `pending_ewash_confirmation`; admin click → `confirmed`.
- **`catalog.service_price()` is the single pricing entry point.** Static Python is the source of truth; DB rows (`ServicePriceRow`, `PromoCodeRow`, `TimeSlotRow`, `CenterRow`, `ClosedDateRow`) override at admin discretion.
- **Refs are `EW-YYYY-####` monotonic per year**, allocated under `with_for_update` on `BookingRefCounterRow`. Survives Railway redeploys.
- **Status FSM is enforced.** 15 statuses, `ALLOWED_STATUS_TRANSITIONS` guards every move, `transition_booking_status` auto-cancels pending reminders on final statuses.
- **Heavy denormalization** on `BookingRow` (customer name, service label, addon snapshot, prices, address) + a `raw_booking_json` snapshot at `models.py:333`. Trade-off: catalog edits can't retroactively rewrite history.
- **In-memory `_bookings` shadow list** in `app/booking.py` is blended into `admin_booking_list()` so unconfirmed drafts stay visible across sessions. DB rows win when present.
- **No reminder dispatcher exists.** `BookingReminderRow` is written at confirmation but no worker reads it. Adding a sender is an explicit out-of-scope item in `plan.md`.
- **Admin auth is single-password** with HMAC-signed session cookie (`timestamp:HMAC-SHA256`, 7-day TTL, httponly + samesite=lax). No CSRF tokens — single-password gate is the only guard.
- **Admin UI is inline HTML strings** (not Jinja templates), dark glassmorphic theme, responsive at 860px. XSS prevention depends on diligent `escape()` calls.
- **PWA is zero-build by deliberate choice.** React + Babel-standalone from unpkg with SRI; `window.X = X` global namespace pattern; component files load in dependency order from `index.html`. A Vite migration is a discussed follow-up but explicitly out of scope for the PWA-backend integration.
- **PWA is anonymous on writes, token-scoped on reads** (planned). No OTP, no password. On first `POST /api/v1/bookings` the server mints an opaque `bookings_token` (SHA-256 hashed at rest, plaintext returned exactly once). The read path takes `X-Ewash-Token` — no `?phone=` parameter exists, so phone enumeration is mechanically impossible.
- **WhatsApp message constraints are baked into the catalog.** List rows clamp to title ≤24, description ≤72; buttons clamp to 3 max with labels ≤20. Pricing display strings (e.g., "Le Complet — 125 DH") are assembled to fit. `test_catalog_baseline.py` asserts the limits.
- **Locale handling is split.** Customer-facing strings in `app/handlers.py` are French only (with hardcoded `_JOURS_FR` because Railway containers default to C locale). Admin portal has fr+en via `app/admin_i18n.py`. PWA has fr+ar via `mobile-app/i18n.js`. No shared translation layer.
- **Debug endpoint `GET /bookings`** at `app/main.py:39-42` leaks the in-memory list with no auth. It is on the integration plan's removal list. Do not call it from anything; do not extend it.

---

## MCP Agent Mail — Multi-Agent Coordination

A mail-like layer that lets coding agents coordinate asynchronously via MCP tools and resources. Provides identities, inbox/outbox, searchable threads, and advisory file reservations with human-auditable artifacts in Git.

### Why It's Useful

- **Prevents conflicts:** Explicit file reservations (leases) for files/globs
- **Token-efficient:** Messages stored in per-project archive, not in context
- **Quick reads:** `resource://inbox/...`, `resource://thread/...`

### Same Repository Workflow

1. **Register identity:**

   ```
   ensure_project(project_key=<abs-path>)
   register_agent(project_key, program, model)
   ```

2. **Reserve files before editing:**

   ```
   file_reservation_paths(project_key, agent_name, ["app/**"], ttl_seconds=3600, exclusive=true)
   ```

3. **Communicate with threads:**

   ```
   send_message(..., thread_id="FEAT-123")
   fetch_inbox(project_key, agent_name)
   acknowledge_message(project_key, agent_name, message_id)
   ```

4. **Quick reads:**
   ```
   resource://inbox/{Agent}?project=<abs-path>&limit=20
   resource://thread/{id}?project=<abs-path>&include_bodies=true
   ```

### Macros vs Granular Tools

- **Prefer macros for speed:** `macro_start_session`, `macro_prepare_thread`, `macro_file_reservation_cycle`, `macro_contact_handshake`
- **Use granular tools for control:** `register_agent`, `file_reservation_paths`, `send_message`, `fetch_inbox`, `acknowledge_message`

### Common Pitfalls

- `"from_agent not registered"`: Always `register_agent` in the correct `project_key` first
- `"FILE_RESERVATION_CONFLICT"`: Adjust patterns, wait for expiry, or use non-exclusive reservation
- **Auth errors:** If JWT+JWKS enabled, include bearer token with matching `kid`

---

## Beads (br) — Dependency-Aware Issue Tracking

Beads provides a lightweight, dependency-aware issue database and CLI (`br` - beads_rust) for selecting "ready work," setting priorities, and tracking status. It complements MCP Agent Mail's messaging and file reservations.

**Important:** `br` is non-invasive—it NEVER runs git commands automatically. You must manually commit changes after `br sync --flush-only`.

### Conventions

- **Single source of truth:** Beads for task status/priority/dependencies; Agent Mail for conversation and audit
- **Shared identifiers:** Use Beads issue ID (e.g., `br-123`) as Mail `thread_id` and prefix subjects with `[br-123]`
- **Reservations:** When starting a task, call `file_reservation_paths()` with the issue ID in `reason`

### Typical Agent Flow

1. **Pick ready work (Beads):**

   ```bash
   br ready --json  # Choose highest priority, no blockers
   ```

2. **Reserve edit surface (Mail):**

   ```
   file_reservation_paths(project_key, agent_name, ["app/**"], ttl_seconds=3600, exclusive=true, reason="br-123")
   ```

3. **Announce start (Mail):**

   ```
   send_message(..., thread_id="br-123", subject="[br-123] Start: <title>", ack_required=true)
   ```

4. **Work and update:** Reply in-thread with progress

5. **Complete and release:**
   ```bash
   br close 123 --reason "Completed"
   br sync --flush-only  # Export to JSONL (no git operations)
   ```
   ```
   release_file_reservations(project_key, agent_name, paths=["app/**"])
   ```
   Final Mail reply: `[br-123] Completed` with summary

### Mapping Cheat Sheet

| Concept                   | Value                             |
| ------------------------- | --------------------------------- |
| Mail `thread_id`          | `br-###`                          |
| Mail subject              | `[br-###] ...`                    |
| File reservation `reason` | `br-###`                          |
| Commit messages           | Include `br-###` for traceability |

---

## bv — Graph-Aware Triage Engine

bv is a graph-aware triage engine for Beads projects (`.beads/beads.jsonl`). It computes PageRank, betweenness, critical path, cycles, HITS, eigenvector, and k-core metrics deterministically.

**Scope boundary:** bv handles _what to work on_ (triage, priority, planning). For agent-to-agent coordination (messaging, work claiming, file reservations), use MCP Agent Mail.

**CRITICAL: Use ONLY `--robot-*` flags. Bare `bv` launches an interactive TUI that blocks your session.**

### The Workflow: Start With Triage

**`bv --robot-triage` is your single entry point.** It returns:

- `quick_ref`: at-a-glance counts + top 3 picks
- `recommendations`: ranked actionable items with scores, reasons, unblock info
- `quick_wins`: low-effort high-impact items
- `blockers_to_clear`: items that unblock the most downstream work
- `project_health`: status/type/priority distributions, graph metrics
- `commands`: copy-paste shell commands for next steps

```bash
bv --robot-triage        # THE MEGA-COMMAND: start here
bv --robot-next          # Minimal: just the single top pick + claim command
```

### Command Reference

**Planning:**
| Command | Returns |
|---------|---------|
| `--robot-plan` | Parallel execution tracks with `unblocks` lists |
| `--robot-priority` | Priority misalignment detection with confidence |

**Graph Analysis:**
| Command | Returns |
|---------|---------|
| `--robot-insights` | Full metrics: PageRank, betweenness, HITS, eigenvector, critical path, cycles, k-core, articulation points, slack |
| `--robot-label-health` | Per-label health: `health_level`, `velocity_score`, `staleness`, `blocked_count` |
| `--robot-label-flow` | Cross-label dependency: `flow_matrix`, `dependencies`, `bottleneck_labels` |
| `--robot-label-attention [--attention-limit=N]` | Attention-ranked labels |

**History & Change Tracking:**
| Command | Returns |
|---------|---------|
| `--robot-history` | Bead-to-commit correlations |
| `--robot-diff --diff-since <ref>` | Changes since ref: new/closed/modified issues, cycles |

**Other:**
| Command | Returns |
|---------|---------|
| `--robot-burndown <sprint>` | Sprint burndown, scope changes, at-risk items |
| `--robot-forecast <id\|all>` | ETA predictions with dependency-aware scheduling |
| `--robot-alerts` | Stale issues, blocking cascades, priority mismatches |
| `--robot-suggest` | Hygiene: duplicates, missing deps, label suggestions |
| `--robot-graph [--graph-format=json\|dot\|mermaid]` | Dependency graph export |
| `--export-graph <file.html>` | Interactive HTML visualization |

### Scoping & Filtering

```bash
bv --robot-plan --label backend              # Scope to label's subgraph
bv --robot-insights --as-of HEAD~30          # Historical point-in-time
bv --recipe actionable --robot-plan          # Pre-filter: ready to work
bv --recipe high-impact --robot-triage       # Pre-filter: top PageRank
bv --robot-triage --robot-triage-by-track    # Group by parallel work streams
bv --robot-triage --robot-triage-by-label    # Group by domain
```

### Understanding Robot Output

**All robot JSON includes:**

- `data_hash` — Fingerprint of source beads.jsonl
- `status` — Per-metric state: `computed|approx|timeout|skipped` + elapsed ms
- `as_of` / `as_of_commit` — Present when using `--as-of`

**Two-phase analysis:**

- **Phase 1 (instant):** degree, topo sort, density
- **Phase 2 (async, 500ms timeout):** PageRank, betweenness, HITS, eigenvector, cycles

### jq Quick Reference

```bash
bv --robot-triage | jq '.quick_ref'                        # At-a-glance summary
bv --robot-triage | jq '.recommendations[0]'               # Top recommendation
bv --robot-plan | jq '.plan.summary.highest_impact'        # Best unblock target
bv --robot-insights | jq '.status'                         # Check metric readiness
bv --robot-insights | jq '.Cycles'                         # Circular deps (must fix!)
```

---

## UBS — Ultimate Bug Scanner

**Golden Rule:** `ubs <changed-files>` before every commit. Exit 0 = safe. Exit >0 = fix & re-run.

### Commands

```bash
ubs file.py file2.py                    # Specific files (< 1s) — USE THIS
ubs $(git diff --name-only --cached)    # Staged files — before commit
ubs --only=python,toml app/             # Language filter (3-5x faster)
ubs --ci --fail-on-warning .            # CI mode — before PR
ubs .                                   # Whole project (ignores .venv/, __pycache__/)
```

### Output Format

```
⚠️  Category (N errors)
    file.py:42:5 – Issue description
    💡 Suggested fix
Exit code: 1
```

Parse: `file:line:col` → location | 💡 → how to fix | Exit 0/1 → pass/fail

### Fix Workflow

1. Read finding → category + fix suggestion
2. Navigate `file:line:col` → view context
3. Verify real issue (not false positive)
4. Fix root cause (not symptom)
5. Re-run `ubs <file>` → exit 0
6. Commit

### Bug Severity

- **Critical (always fix):** SQL injection, command injection, XSS, secret leakage, broken auth
- **Important (production):** Unhandled exceptions, resource leaks, missing input validation
- **Contextual (judgment):** TODO/FIXME, `print()` debugging, dead code

---

## RCH — Remote Compilation Helper

RCH offloads `cargo build`, `cargo test`, `cargo clippy`, and other compilation commands to a fleet of 8 remote Contabo VPS workers instead of building locally. This prevents compilation storms from overwhelming csd when many agents run simultaneously.

**RCH is installed at `~/.local/bin/rch` and is hooked into Claude Code's PreToolUse automatically.** Most of the time you don't need to do anything if you are Claude Code — builds are intercepted and offloaded transparently.

To manually offload a build:

```bash
rch exec -- cargo build --release
rch exec -- cargo test
rch exec -- cargo clippy
```

Quick commands:

```bash
rch doctor                    # Health check
rch workers probe --all       # Test connectivity to all 8 workers
rch status                    # Overview of current state
rch queue                     # See active/waiting builds
```

If rch or its workers are unavailable, it fails open — builds run locally as normal.

**Note for Codex/GPT-5.2:** Codex does not have the automatic PreToolUse hook, but you can (and should) still manually offload compute-intensive compilation commands using `rch exec -- <command>`. This avoids local resource contention when multiple agents are building simultaneously.

---

## ast-grep vs ripgrep

**Use `ast-grep` when structure matters.** It parses code and matches AST nodes, ignoring comments/strings, and can **safely rewrite** code.

- Refactors/codemods: rename APIs, change import forms
- Policy checks: enforce patterns across a repo
- Editor/automation: LSP mode, `--json` output

**Use `ripgrep` when text is enough.** Fastest way to grep literals/regex.

- Recon: find strings, TODOs, log lines, config values
- Pre-filter: narrow candidate files before ast-grep

### Rule of Thumb

- Need correctness or **applying changes** → `ast-grep`
- Need raw speed or **hunting text** → `rg`
- Often combine: `rg` to shortlist files, then `ast-grep` to match/modify

### Python Examples

```bash
# Find structured code (ignores comments)
ast-grep run -l python -p 'def $NAME($$$ARGS) -> $RET: $$$BODY'

# Find all .get() calls with default
ast-grep run -l python -p '$EXPR.get($KEY, $DEFAULT)'

# Quick textual hunt
rg -n 'print\(' -t py

# Combine speed + precision
rg -l -t py 'session_scope' | xargs ast-grep run -l python -p 'with session_scope($ENGINE) as $S: $$$BODY' --json
```

---

## Morph Warp Grep — AI-Powered Code Search

**Use `mcp__morph-mcp__warp_grep` for exploratory "how does X work?" questions.** An AI agent expands your query, greps the codebase, reads relevant files, and returns precise line ranges with full context.

**Use `ripgrep` for targeted searches.** When you know exactly what you're looking for.

**Use `ast-grep` for structural patterns.** When you need AST precision for matching/rewriting.

### When to Use What

| Scenario                                             | Tool        | Why                                    |
| ---------------------------------------------------- | ----------- | -------------------------------------- |
| "How does the two-step confirmation flow work?"      | `warp_grep` | Exploratory; don't know where to start |
| "Where is the ref counter allocated?"                | `warp_grep` | Need to understand architecture        |
| "Find all uses of `service_price`"                   | `ripgrep`   | Targeted literal search                |
| "Find files with `print(`"                           | `ripgrep`   | Simple pattern                         |
| "Replace all `dict.get(k, None)` with `dict.get(k)`" | `ast-grep`  | Structural refactor                    |

### warp_grep Usage

```
mcp__morph-mcp__warp_grep(
  repoPath: "/Users/osekkat/ewash/ewash",
  query: "How does the pending_ewash_confirmation status get promoted to confirmed?"
)
```

Returns structured results with file paths, line ranges, and extracted code snippets.

### Anti-Patterns

- **Don't** use `warp_grep` to find a specific function name → use `ripgrep`
- **Don't** use `ripgrep` to understand "how does X work" → wastes time with manual reads
- **Don't** use `ripgrep` for codemods → risks collateral edits

<!-- bv-agent-instructions-v1 -->

---

## Beads Workflow Integration

This project uses [beads_rust](https://github.com/Dicklesworthstone/beads_rust) (`br`) for issue tracking. Issues are stored in `.beads/` and tracked in git.

**Important:** `br` is non-invasive—it NEVER executes git commands. After `br sync --flush-only`, you must manually run `git add .beads/ && git commit`.

### Essential Commands

```bash
# View issues (launches TUI - avoid in automated sessions)
bv

# CLI commands for agents (use these instead)
br ready              # Show issues ready to work (no blockers)
br list --status=open # All open issues
br show <id>          # Full issue details with dependencies
br create --title="..." --type=task --priority=2
br update <id> --status=in_progress
br close <id> --reason "Completed"
br close <id1> <id2>  # Close multiple issues at once
br sync --flush-only  # Export to JSONL (NO git operations)
```

### Workflow Pattern

1. **Start**: Run `br ready` to find actionable work
2. **Claim**: Use `br update <id> --status=in_progress`
3. **Work**: Implement the task
4. **Complete**: Use `br close <id>`
5. **Sync**: Run `br sync --flush-only` then manually commit

### Key Concepts

- **Dependencies**: Issues can block other issues. `br ready` shows only unblocked work.
- **Priority**: P0=critical, P1=high, P2=medium, P3=low, P4=backlog (use numbers, not words)
- **Types**: task, bug, feature, epic, question, docs
- **Blocking**: `br dep add <issue> <depends-on>` to add dependencies

### Session Protocol

**Before ending any session, run this checklist:**

```bash
git status              # Check what changed
git add <files>         # Stage code changes
br sync --flush-only    # Export beads to JSONL
git add .beads/         # Stage beads changes
git commit -m "..."     # Commit everything together
git push                # Push to remote
```

### Best Practices

- Check `br ready` at session start to find available work
- Update status as you work (in_progress → closed)
- Create new issues with `br create` when you discover tasks
- Use descriptive titles and set appropriate priority/type
- Always `br sync --flush-only && git add .beads/` before ending session

<!-- end-bv-agent-instructions -->

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Sync beads** - `br sync --flush-only` to export to JSONL
5. **Hand off** - Provide context for next session

---

## cass — Cross-Agent Session Search

`cass` indexes prior agent conversations (Claude Code, Codex, Cursor, Gemini, ChatGPT, etc.) so we can reuse solved problems.

**Rules:** Never run bare `cass` (TUI). Always use `--robot` or `--json`.

### Examples

```bash
cass health
cass search "async runtime" --robot --limit 5
cass view /path/to/session.jsonl -n 42 --json
cass expand /path/to/session.jsonl -n 42 -C 3 --json
cass capabilities --json
cass robot-docs guide
```

### Tips

- Use `--fields minimal` for lean output
- Filter by agent with `--agent`
- Use `--days N` to limit to recent history

stdout is data-only, stderr is diagnostics; exit code 0 means success.

Treat cass as a way to avoid re-solving problems other agents already handled.

---

Note for Codex/GPT-5.2:

You constantly bother me and stop working with concerned questions that look similar to this:

```
Unexpected changes (need guidance)

- Working tree still shows edits I did not make in requirements.txt, app/handlers.py, mobile-app/booking.jsx, tests/test_booking_persistence.py. Please advise whether to keep/commit/revert these before any further work. I did not touch them.

Next steps (pick one)

1. Decide how to handle the unrelated modified files above so we can resume cleanly.
2. Triage br-### (pytest failures) and br-### (admin auth regression).
3. If you want a full suite run later, fix conformance/clippy blockers and re-run pytest.
```

NEVER EVER DO THAT AGAIN. The answer is literally ALWAYS the same: those are changes created by the potentially dozen of other agents working on the project at the same time. This is not only a common occurrence, it happens multiple times PER MINUTE. The way to deal with it is simple: you NEVER, under ANY CIRCUMSTANCE, stash, revert, overwrite, or otherwise disturb in ANY way the work of other agents. Just treat those changes identically to changes that you yourself made. Just fool yourself into thinking YOU made the changes and simply don't recall it for some reason.

---

## Note on Built-in TODO Functionality

Also, if I ask you to explicitly use your built-in TODO functionality, don't complain about this and say you need to use beads. You can use built-in TODOs if I tell you specifically to do so. Always comply with such orders.
