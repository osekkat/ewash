# ADR 0001: Token-scoped reads for the PWA Bookings tab

- **Status:** Accepted
- **Date:** 2026-05-14
- **Owner:** Ewash backend team
- **Related work:** `br-ewash-6pa.1.2` (migration 0006 / `customer_tokens` table), `br-ewash-6pa.3.2` (`mint_customer_token` / `verify_customer_token`), `br-ewash-6pa.3.3` (`list_bookings_for_token`), `br-ewash-6pa.4.17` (`POST /api/v1/tokens/revoke`)

## Context

The PWA shows customers their own booking history through a `GET /api/v1/bookings` endpoint. The WhatsApp bot already identifies customers by phone (Meta-verified at the carrier level), but the PWA has no equivalent verification channel. The product constraints for v1 were stated explicitly:

- **No OTP**. Customers should be able to make a booking in under a minute without juggling another inbox or SMS.
- **No password**. We are not running a login form, a forgot-password flow, or a session manager.
- **No phone enumeration**. The WhatsApp number space in Morocco is small enough that an attacker could iterate `+212 6 X X X X X X X X` and pull every customer's history if the read path accepted phone as a query parameter.

Bookings carry sensitive metadata: vehicle make and color, plate, home address, scheduled time. Treating this as PII is the right default.

The team needed an auth mechanism with effectively zero customer-facing friction that nevertheless prevents another user from reading someone else's bookings.

## Decision

Reads on `GET /api/v1/bookings` are scoped by an **opaque, server-minted token** that the PWA stores in `localStorage` and sends in the `X-Ewash-Token` request header. The DB stores only the SHA-256 hash of the token; the plaintext is returned to the client exactly once, in the response body of the first `POST /api/v1/bookings` for that device.

There is no `?phone=` query parameter, no JWT, no cookie, no OTP. The server cannot enumerate bookings by phone because the API does not expose that path.

Token minting and verification live in `app/persistence.py`:

- `mint_customer_token(phone)` returns the plaintext token and persists `(phone, sha256_hash)` in `customer_tokens`.
- `verify_customer_token(plaintext, *, expected_phone=None)` returns the matching phone (or `None`), bumping `last_used_at`. The `expected_phone` kwarg is the anti-token-theft guard for write paths that already know whose token it is.

Multiple tokens per phone are allowed (one per device that ever booked). They remain valid indefinitely until a future admin-revocation pass purges stale entries.

## Rationale

| Option | Verdict | Why |
|---|---|---|
| Phone-keyed reads | Rejected | Enables enumeration; the Moroccan WhatsApp number space is bruteforceable. |
| OTP / SMS magic link | Rejected | Violates the "no friction" constraint and adds a second messaging surface to operate. |
| Email login | Rejected | Customers don't supply email in the booking flow. |
| OAuth (Google / Apple) | Rejected | Adds a third-party identity dependency for a product whose customer relationship is built on WhatsApp. |
| JWT | Rejected | All the complexity of a real auth system (signing keys, rotation, refresh, revocation) for a use case that doesn't benefit from any of it. |
| Session cookies | Rejected | Cookies imply `allow_credentials: true` in CORS, which restricts the regex-based preview-origin path used by `br-ewash-6pa.2.3` and re-introduces enumerability for whoever currently holds the cookie. |
| **Opaque tokens, hashed at rest** | Accepted | Cheap to mint and verify, no PKI, revocable by row deletion. A DB dump never yields a usable session token. From the customer's perspective the experience is "no auth required". |

The hashed-at-rest property matters: even an internal admin or a security incident reader cannot impersonate a customer just by looking at the `customer_tokens` table. They would need to observe the plaintext during a live request, which is the same threat model as any bearer-token API.

## Consequences

- **localStorage clearing loses history visibility.** Customers who wipe browser data on their device no longer see their bookings in the PWA. Their data remains intact in Postgres and is reachable via the WhatsApp bot ("voir mes réservations"). This is the explicit tradeoff for zero auth friction.
- **No cross-device sync in v1.** A customer who books on their phone and opens the PWA on their tablet has no way to authenticate the tablet as theirs. A "WhatsApp-delivered magic link" is the natural v2 path (the team owns the WhatsApp number; sending the token via WA reuses the existing trust anchor without re-introducing phone enumerability).
- **No client-side rate-limit-bypass risk.** The token doesn't grant new permissions, just bound-narrowed reads. Even if it leaks, the only data exposed is the booking metadata of the affected customer.
- **CORS stays simple.** Because we use a header, not a cookie, `allow_credentials: false` works and the regex-matched preview-origin path (`https://ewash-mobile-app-*.vercel.app`) remains supported.
- **Future revocation work is local.** Deleting a row from `customer_tokens` revokes a session. No JWT denylist propagation, no cookie expiry tuning. `POST /api/v1/tokens/revoke` (br-4.17) is a one-row delete. `DELETE /api/v1/me` (br-4.18) cascades via the FK.
- **Indefinite token lifetime in v1.** Until an admin-side janitor lands, tokens never expire. `last_used_at` is captured on every verify, so a future pass can purge tokens unused for, say, 90 days without affecting active customers.

## Implementation invariants

These are non-negotiable for any code that touches `customer_tokens` or the read endpoints:

1. The plaintext is **never logged**. Only the hash, or a redacted prefix, may appear in logs.
2. The plaintext is **returned exactly once**, in the JSON body of `POST /api/v1/bookings`. Subsequent reads of the same booking row do not echo it back.
3. The hash column has a `UNIQUE` constraint. Collisions of SHA-256 over 32-byte random plaintexts are not a realistic concern, but the column-level uniqueness makes the lookup `O(1)` and surfaces bugs early.
4. `GET /api/v1/bookings` **must not** accept a phone in any form (query param, body, header). The bookings-list query takes the verified token's customer_phone as its only filter.
5. The booking-write path (`POST /api/v1/bookings`) is unauthenticated. Rate limits, idempotency via `client_request_id`, and the two-step staff confirmation invariant compensate for the open-write surface.

## Alternatives explicitly considered and rejected

- **Server-issued opaque tokens stored in a cookie.** Would force `allow_credentials: true`, which is incompatible with the `*.vercel.app` regex-allow-list pattern used for Vercel preview deploys. Header-based delivery sidesteps this.
- **Hash-then-re-randomize on every request (rolling tokens).** Adds operational complexity (clients that mid-flight crash or lose connectivity end up with two tokens out of sync) for no realistic threat model gain.
- **Server-side session table keyed by IP.** Rejected: mobile IPs change constantly (carrier NAT, Wi-Fi handoff), and the auth model would either lock customers out frequently or be useless.

## Open questions

- **Token expiry / revocation cadence.** When and how the admin janitor purges stale rows is out of scope for v1; ticket as a follow-up when the table reaches operational size.
- **Multi-phone reassignment.** If a customer changes their phone number (rare in practice in Morocco), what happens to the existing token? Current answer: nothing — the token still points to the OLD phone via `customer_phone`. A future bead can wire this into the admin "merge customers" flow.
