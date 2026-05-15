# Ewash

WhatsApp-native eco car-wash service for Bouskoura / Casablanca, Morocco. Pre-launch.

The repo ships two runtimes that do not share traffic today:

- **`app/`** — FastAPI backend on Railway. French WhatsApp bot on Meta Cloud API v21.0 plus a password-gated admin portal at `/admin`. Postgres via SQLAlchemy + Alembic. Version label `v0.3.0-alpha17`.
- **`mobile-app/`** — React 18 PWA on Vercel. Zero-build (React + Babel-standalone from unpkg, SRI hashes). French + Arabic with RTL.

`plan.md` is the integration plan: an `/api/v1/*` router that will let the PWA become a second client of the same domain core. Not implemented yet — the PWA currently uses hardcoded mock data.

## Architecture

```
Customer WhatsApp          POST /webhook                  PWA (Vercel, mock data today)
      │                         │                                  │
      ▼                         ▼                                  ▼
Meta Cloud API v21.0 ─▶ app/main.py ─▶ app/handlers.py    (planned: app/api.py)
      ▲                                      │                     │
      │                                      ▼                     │
      └────── meta.send_* ◀── app/booking.py (Booking dataclass) ◀─┘
                                             │
                                             ▼
                                      app/persistence.py
                                             │
              ┌──────────────────────────────┼──────────────────────────────┐
              ▼                              ▼                              ▼
        Postgres (Railway)             app/catalog.py              app/notifications.py
        22 tables / 5 migrations        (pricing source              (Meta template
                                          of truth)                   to staff phone)
```

### Two clients, one domain core

The WhatsApp bot and the (planned) PWA are two clients of the same backend. Both write to the same `bookings` table via the same `assign_booking_ref` + `persist_confirmed_booking` helpers; a new `source` column (`whatsapp` | `api` | `admin`) distinguishes them. Pricing flows through `catalog.service_price()` from a single static catalog in `app/catalog.py`, so the PWA never carries its own prices.

| Surface | Inbound | Auth | Status produced |
|---------|---------|------|-----------------|
| `POST /webhook` | Customer DM via Meta Cloud API | HMAC-SHA256 | `pending_ewash_confirmation` |
| `POST /api/v1/bookings` (planned) | PWA fetch | Rate limit; CORS | `pending_ewash_confirmation` |
| `POST /admin/bookings/confirm` | Operator click | Admin session cookie | `confirmed` (only writer) |
| `GET /api/v1/bookings` (planned) | PWA fetch | `X-Ewash-Token` (SHA-256-hashed at rest) | n/a |

The PWA `bookings_token` is minted server-side at first booking, returned exactly once in the response, and persisted in `localStorage`. Read paths take the token in a request header — there is no `?phone=…` parameter, so phone enumeration is mechanically impossible.

## Customer flow (today)

1. Customer DMs the Meta WhatsApp number → webhook delivered → HMAC-SHA256 verified
2. `app/handlers.py` drives a 22-state button/list conversation. Sessions are in-memory keyed by phone, 2-hour idle TTL, reset on Railway redeploy by design.
3. On confirm, the bot allocates an `EW-YYYY-####` reference (atomic under `with_for_update` on `BookingRefCounterRow`), persists the booking at `status = pending_ewash_confirmation`, and sends a Meta template alert to the staff WhatsApp phone.
4. Staff opens `/admin/bookings` and clicks **Confirmer eWash**. Only then does the booking move to `status = confirmed` and the H-2 reminder row get written.

The two-step staff confirmation is deliberate — staff verifies feasibility (location, vehicle, slot capacity) before Ewash commits a slot.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness probe, returns version |
| GET | `/webhook` | Meta one-time verification challenge |
| POST | `/webhook` | Inbound messages (HMAC-SHA256 verified) |
| GET, POST | `/admin` | Password gate, dashboard |
| GET | `/admin/{bookings, customers, prices, promos, reminders, notifications, closed-dates, time-slots, centers, copy}` | Admin pages |
| POST | `/admin/bookings/confirm` | Promote `pending_ewash_confirmation` → `confirmed` |
| POST | `/admin/{prices, promos, reminders, notifications, closed-dates, time-slots, centers, copy}` | Catalog upserts |
| POST | `/internal/conversations/abandon` | Cron-only, marks inactive conversations stale |

## Local dev — backend

The backend uses pip + a venv. No poetry, pipenv, uv, or conda.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in META_APP_SECRET, META_VERIFY_TOKEN, META_ACCESS_TOKEN, ADMIN_PASSWORD, DATABASE_URL
alembic upgrade head
uvicorn app.main:app --reload
```

Expose `http://localhost:8000` with ngrok and paste `<ngrok>/webhook` into the Meta dashboard.

### Tests

```bash
source .venv/bin/activate
pytest                                    # full suite — 14 files, ~68 tests
pytest tests/test_booking_persistence.py
pytest -k returning_customer              # name filter
pytest -s                                 # show stdout
```

Tests run against SQLite in-memory; Postgres-only behaviour (partial indexes, check constraints, `with_for_update` semantics) is exercised only in production.

## Local dev — PWA

The PWA is zero-build. There is no `package.json`. React 18.3.1, ReactDOM, and `@babel/standalone` 7.29.0 are pulled from unpkg with SRI hashes. Files self-register on `window` and load in dependency order from `index.html`.

```bash
cd mobile-app
python3 -m http.server 5173
# open http://localhost:5173
```

After any `mobile-app/*.jsx` change, reload in a browser and walk the relevant flow — there is no type checker.

## Deploy — backend (Railway)

1. Push to GitHub.
2. Railway dashboard → **New Project** → **Deploy from GitHub repo**.
3. Railway auto-detects Nixpacks (Python 3.12 per `runtime.txt`).
4. **Variables** tab: add every key from `.env.example`. Railway sets `PORT`.
5. Deploy. Watch logs for `Application startup complete`. Then **Settings** → **Networking** → **Generate Domain**. The current production domain is `https://web-production-1a800.up.railway.app` (kept in sync with `mobile-app/config.js`).
6. Register the webhook in Meta:
   - developers.facebook.com → your app → WhatsApp → **Configuration**.
   - Callback URL: `https://<railway-domain>/webhook`.
   - Verify token: the exact value of `META_VERIFY_TOKEN`.
   - Click **Vérifier et enregistrer**.
   - Under **Champs de webhook**, subscribe to **messages**.
7. Replace the 24-hour Meta token with a long-lived System User token:
   - business.facebook.com → Paramètres → Utilisateurs système → **Ajouter**.
   - Role: Admin. Assign the app with `whatsapp_business_messaging` + `whatsapp_business_management` permissions.
   - Generate token (never expires) → paste into Railway's `META_ACCESS_TOKEN` → redeploy.

## Deploy — PWA (Vercel)

Set the Vercel project root to `mobile-app/`. `mobile-app/vercel.json` declares cache headers (long-immutable on icons, short must-revalidate on JSX/JS/CSS, `no-store` on `service-worker.js`) and `Permissions-Policy: geolocation=(self)`.

## Staff booking alerts

The admin portal exposes `/admin/notifications` to configure the staff WhatsApp alert sent when a customer confirms a booking:

- Staff WhatsApp phone, digits only (e.g. `212665883062`)
- Approved template name (e.g. `new_booking_alert`)
- Template language (e.g. `fr`)

The template body receives 10 positional parameters in this order: `{{1}}` event type, `{{2}}` reference, `{{3}}` customer name, `{{4}}` phone, `{{5}}` vehicle, `{{6}}` service, `{{7}}` date/slot, `{{8}}` location, `{{9}}` price, `{{10}}` note.

## Project layout

```
app/                              FastAPI backend
  main.py                         /webhook, /health, /admin mount
  config.py                       pydantic-settings — Meta creds, DB URL, admin auth
  meta.py                         Meta Cloud API client — HMAC verify, send_*
  handlers.py                     WhatsApp state machine (22 states)
  state.py                        In-memory session dict (2h TTL)
  booking.py                      Booking dataclass + in-memory shadow + ref counter
  catalog.py                      Pricing source of truth + static catalog + DB overrides
  persistence.py                  All DB writes, dashboard queries
  models.py                       22 SQLAlchemy models + ALLOWED_STATUS_TRANSITIONS
  db.py                           Engine, session_scope, init_db, backfills
  notifications.py                Staff Meta template alert
  admin.py                        Multi-page admin portal — session cookie, all CRUD
  admin_i18n.py                   fr/en strings for the admin portal
  static/                         Tariff JPGs

migrations/versions/              Alembic — 5 migrations
tests/                            14 files, ~68 tests, SQLite in-memory

mobile-app/                       Zero-build React 18 PWA
  index.html                      Loads React, ReactDOM, Babel-standalone, then JSX in order
  app.jsx                         Shell — splash, language picker, tab routing, modals
  booking.jsx                     11-step booking flow (hardcoded catalog)
  screens.jsx                     Home / Bookings / Services / Profile / Support
  components.jsx                  Shared UI kit
  auth.jsx                        Splash + language picker
  icons.jsx                       SVG icon set
  i18n.js                         FR + AR strings, day/month arrays, RTL
  tweaks-panel.jsx                Dev/design controls (variant, theme, language)
  service-worker.js               Network-first, cache fallback
  manifest.webmanifest            PWA manifest
  vercel.json                     Cache headers, perms policy
  styles.css                      Design tokens + eco/premium variants × light/dark

plan.md                           PWA ↔ backend integration plan (not yet built)
AGENTS.md                         Guidelines for AI coding agents — authoritative reference
```

## Key invariants

- **Two-step staff confirmation.** `persist_confirmed_booking()` writes `pending_ewash_confirmation` only. `confirm_booking_by_ewash()` (under `with_for_update`) is the only writer to `confirmed`; the H-2 reminder row is created here. The planned `/api/v1/bookings` POST will also write `pending_ewash_confirmation` — the API will not expose a confirm endpoint.
- **`catalog.service_price()` is the single pricing function.** Static Python in `app/catalog.py` is the source of truth; DB rows (`ServicePriceRow`, `PromoDiscountRow`) override at admin discretion. Post-integration, the PWA will carry no prices of its own.
- **`EW-YYYY-####` references are monotonic per year**, allocated under `with_for_update` on `BookingRefCounterRow`. Survives Railway redeploys.
- **Status FSM is enforced.** 15 statuses; `ALLOWED_STATUS_TRANSITIONS` in `app/models.py` guards every transition. `transition_booking_status()` auto-cancels pending reminders on terminal statuses.

## Roadmap

- [x] WhatsApp echo bot
- [x] French booking flow — cars + moto, home or center, promos, post-confirmation detailing upsell
- [x] Postgres persistence, admin portal, returning-customer recall, staff alerts
- [ ] `/api/v1/*` router; PWA becomes a second client of the same domain core (see `plan.md`)
- [x] Reminder dispatcher — `POST /internal/reminders/dispatch` ships H-2 `BookingReminderRow` rows on a cron cadence (see `docs/runbooks/reminders.md`)
- [ ] Production Meta number swap via Coexistence

## Documentation

- `AGENTS.md` — contributor guidelines, toolchain rules, code-editing discipline, testing policy, and the full set of product invariants (read this first).
- `CHANGELOG.md` — versioned release notes (Keep a Changelog format).
- `plan.md` — PWA ↔ backend integration plan (in progress; see `br ready` for live status).
- `docs/adr/` — architectural decision records (planned, see `br-ewash-6pa.8.10`).
- `docs/runbooks/` — ops procedures for staging dry-runs, production migration apply, rollback, and common API failures (planned, see `br-ewash-6pa.8.11`).
- `docs/compliance/` — Loi 09-08 / GDPR data-erasure policy and operator runbook.
- `.beads/` — issue tracker state; use `br ready` / `bv --robot-triage` for actionable work.
