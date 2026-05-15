# Loi 09-08 / GDPR — Data Erasure Policy

Status: working draft, summary pending counsel review.
Owner: Ewash operations team.
Last updated: 2026-05-15.

> This document describes how Ewash satisfies a customer's right to erasure
> ("droit à l'effacement") under Moroccan personal-data protection law
> (Loi 09-08 of 18 February 2009, supervised by the **CNDP**, Commission
> Nationale de contrôle de la protection des Données à caractère Personnel).
> It also covers the equivalent GDPR Article 17 obligation for any EU-resident
> customer who books through the WhatsApp bot or PWA. Every claim about which
> rows are touched is cross-referenced to specific lines in the codebase;
> reviewers should be able to verify each statement directly against the
> source tree.

---

## 1. Legal basis

Loi 09-08 grants any data subject the right to obtain rectification or
erasure of their personal data held by a data controller. The CNDP's
guidance treats this as both a self-serve right (the customer must be able
to act without bureaucratic friction) and an operator-assisted right (the
controller must be able to respond to a written request within a documented
delay, typically 30 days).

Ewash satisfies both modes:

- **Customer self-serve** — anyone with a valid `bookings_token` (PWA
  customer identity) can issue `DELETE /api/v1/me` from the Profile screen
  after typing a confirm phrase. The handler immediately deletes every
  customer-side row and anonymizes the customer's bookings; no operator is
  in the loop.
- **Operator-assisted** — an admin can run the same erasure from
  `/admin/customers` against any phone in the database. Both paths share
  the same helper (`anonymize_customer`) so the resulting state is
  identical, and both write to the same `data_erasure_audit` table.

> **Legal disclaimer (summary pending counsel review).** This document
> summarizes the operational implementation; the article-number citation,
> the precise CNDP correspondence protocol, and the EU data-subject
> notification template are still pending review with counsel. Until that
> review lands, treat the legal-basis paragraph as a working summary and not
> a regulatory commitment.

---

## 2. What gets erased

### Tables fully purged (rows deleted)

The customer self-serve and admin-initiated paths both call
`persistence.anonymize_customer` (`app/persistence.py:1647-1782`). That
helper issues `DELETE` statements against four tables for the calling
phone:

| Table                       | Purpose                                | Code reference                          |
| --------------------------- | -------------------------------------- | --------------------------------------- |
| `customer_tokens`           | PWA bookings_token rows (SHA-256 hash) | `app/persistence.py:1705-1714`          |
| `customer_names`            | Returning-customer name history        | `app/persistence.py:1705-1714`          |
| `customer_vehicles`         | Make / model / colour history          | `app/persistence.py:1705-1714`          |
| `conversation_sessions`     | In-progress WhatsApp state             | `app/persistence.py:1705-1714`          |
| `conversation_events`       | WhatsApp event trail (FK chained)      | `app/persistence.py:1696-1704`          |

Conversation events are deleted first because the FK chain from
`conversation_sessions.id` cascades on the SQLite test path; the same
statement runs harmlessly on Postgres where the FK already cascades.

### Tables anonymized in place (rows preserved)

The `bookings` table is **not deleted**. Slot history is preserved for
revenue accounting and for staff to honour the two-step confirmation
invariant (a deleted row would silently free a confirmed slot). Every
booking owned by the calling phone is anonymized in-place — PII fields are
overwritten, accounting fields are preserved
(`app/persistence.py:1716-1731`).

| `BookingRow` field        | After anonymization                | Source                          |
| ------------------------- | ---------------------------------- | ------------------------------- |
| `customer_phone`          | `DEL-<sha256(phone)[:12]>` sentinel | `app/persistence.py:1688-1689, 1755-1770` |
| `customer_name`           | `"Anonyme"`                        | `app/persistence.py:1721`       |
| `car_model`               | `""` (empty string)                | `app/persistence.py:1722`       |
| `color`                   | `""`                               | `app/persistence.py:1723`       |
| `address`                 | `""`                               | `app/persistence.py:1724`       |
| `address_text`            | `""`                               | `app/persistence.py:1725`       |
| `location_name`           | `""`                               | `app/persistence.py:1726`       |
| `location_address`        | `""`                               | `app/persistence.py:1727`       |
| `note`                    | `""`                               | `app/persistence.py:1728`       |
| `latitude`, `longitude`   | `None`                             | `app/persistence.py:1729-1730`  |
| `raw_booking_json`        | `"{}"` (the full PII snapshot is wiped) | `app/persistence.py:1731`  |

Preserved fields (these survive anonymization):

- `id`, `ref` (the `EW-YYYY-####` series — needed for revenue continuity)
- `status` and the entire status-event audit chain
- `created_at` (timestamp of the original booking)
- `service_id`, `service_label`, `service_bucket`, `slot`, `date_iso`
- `price_dh`, `addon_price_dh`, `total_price_dh` (financial record)
- `source` (`whatsapp` | `api` | `admin`) — needed for analytics

The `customers` row itself is also handled in `anonymize_customer`
(`app/persistence.py:1734-1760`):

- If no anonymized customer exists with the target sentinel phone, the
  original row is renamed: `display_name` set to `"Anonyme"`, WhatsApp
  profile/wa_id wiped, last-stage fields cleared, and `phone` rewritten to
  `DEL-<hash>`. On Postgres this triggers `ON UPDATE CASCADE` against
  `bookings.customer_phone` so the FK rewrite is atomic
  (`migrations/versions/20260514_0006_pwa_integration.py:183-199`).
- If the sentinel customer already exists (the same real phone was erased
  before and has since booked again), the new bookings are merged into the
  existing sentinel via an explicit `UPDATE bookings SET customer_phone`
  (`app/persistence.py:1754-1758`) and the duplicate row is deleted. This
  preserves the audit timeline across repeat erasures.

### Tables not touched

The erasure helper does **not** touch the following — they carry no PII or
are operational rows whose loss would impair Ewash's operations:

- `booking_reminders` (H-2 staff reminders — operational, no PII)
- `booking_status_events` (status transition audit — keyed on booking_id,
  not phone; survives along with the anonymized booking)
- `booking_ref_counter`, `services`, `service_prices`, `promo_codes`,
  `time_slots`, `centers`, `closed_dates`, `staff_notifications` (catalog /
  configuration tables)
- `data_erasure_audit` (the audit itself — see Section 4)

---

## 3. How to trigger erasure

### 3.1 Customer self-serve — `DELETE /api/v1/me`

Route: `app/api.py:1171-1240`.

**Authentication:** `X-Ewash-Token` header carrying the customer's PWA
booking token (minted at first `POST /api/v1/bookings`,
`app/api.py:1202-1217`).

**Body:** JSON with a single field whose value is the literal phrase
`I confirm I want to delete my data`. This is enforced by Pydantic's
`Literal` on `MeDeleteRequest.confirm` (`app/api_schemas.py:236-244`); any
other value yields a 422 from the framework before the handler runs. The
phrase is also exported as a module constant
(`app/api_schemas.py:236 ME_DELETE_CONFIRM_PHRASE`) so the PWA, the test
suite, and any future translation layer reference the same string.

**Rate limit:** 3/hour per token + 600/hour per IP umbrella
(`app/api.py:1172-1173`, defaults in `app/config.py:58, 65`). Legitimate
use is a single tap; repeated calls only happen during abuse or accidental
retries.

**Success response:** 200 with
`MeDeleteResponse(deleted_count: int, anonymized_bookings: int)`
(`app/api_schemas.py:247-249`).

**PWA invocation:** the Profile screen's "Supprimer mon compte" sheet
forces the customer to type the literal phrase before the Confirm button
activates (`mobile-app/screens.jsx:1171-1210`); the handler then sends
`{ confirm: 'I confirm I want to delete my data' }` over HTTPS.

### 3.2 Admin-initiated — `POST /admin/customers/{phone}/erase`

Route: `app/admin.py:1039-1073`.

**Authentication:** admin session cookie (set after password login at
`POST /admin`).

**Form fields:**

- `confirm` must equal the literal string `ERASE` (operator types it into
  the form to avoid mis-clicks).
- `notes` is an optional free-text field for the audit row (capped at 500
  characters, see `app/admin.py:1046`).

The actor string captures session-timestamp + client-host so the audit
row distinguishes which admin session ran the erasure
(`app/admin.py:1057-1060`).

**Review surface:** `GET /admin/erasures` (`app/admin.py:850-895`, nav
entry at `app/admin.py:41`) renders the last 100 erasure rows with an
optional `actor` filter so compliance reviewers can split self-serve vs
admin-initiated.

---

## 4. Audit trail

### 4.1 Schema

Table: `data_erasure_audit` (migration
`migrations/versions/20260514_0006_pwa_integration.py:160-181`, ORM model
`app/models.py:722-750`).

| Column                | Type            | Notes                                    |
| --------------------- | --------------- | ---------------------------------------- |
| `id`                  | Integer PK      | Autoincrement                            |
| `phone_hash`          | `String(64)`    | Full SHA-256 hex of the original phone   |
| `actor`               | `String(64)`    | `customer_self_serve` or `admin:<ts>:<host>` |
| `deleted_count`       | Integer         | Customer-side rows physically deleted    |
| `anonymized_bookings` | Integer         | Booking rows scrubbed in place           |
| `performed_at`        | `DateTime(tz)`  | Server default `now()`; indexed DESC     |
| `notes`               | `Text`, nullable | Operator-supplied notes (admin path only) |

The table is append-only by convention; no UPDATE or DELETE statements
touch existing rows (see model docstring at `app/models.py:723-732`).

### 4.2 What's stored vs what's not

- **Stored:** the SHA-256 hex digest of the customer phone, never the raw
  phone. The hash is computed in `anonymize_customer`
  (`app/persistence.py:1688`) and inserted into the audit row at
  `app/persistence.py:1772-1780`.
- **Stored:** the actor label (so we can answer "how many customers did
  the operator erase last quarter vs how many self-served").
- **Stored:** row counts (so we can show throughput in the admin view).
- **Not stored:** the raw phone, the customer name, the booking refs.

Why the full 64-char digest and not a truncated prefix: the audit log is
meant to survive standalone (the booking-row FK uses a truncated 12-char
prefix on `DEL-<hash>` for index efficiency, but the audit row keeps the
full digest so it stays collision-resistant for long-tail compliance
reporting). See the rationale block at `app/persistence.py:1677-1680`.

### 4.3 Retention

The intended retention policy for `data_erasure_audit` rows is **seven
years**, matching the standard Moroccan accounting retention window for
financial transactions. After that the rows should be purged
programmatically; no purge job exists yet (see Section 6).

Note that the audit row carries no PII — only a hash — so the seven-year
retention is itself privacy-preserving. The window is set by accounting
practice, not by Loi 09-08.

---

## 5. Operator runbook

### 5.1 Responding to a CNDP complaint

1. Identify the complainant's phone number from the CNDP correspondence
   (typically a normalized E.164 string like `212611204502`).
2. In a one-off shell on Railway, compute the SHA-256 hex digest of the
   phone:
   ```
   railway run python -c "import hashlib; print(hashlib.sha256(b'212611204502').hexdigest())"
   ```
3. Open `/admin/erasures` and filter by phone hash (paste the full 64-char
   digest into the search box, or browse and Ctrl-F the prefix in the
   rendered HTML). If the row is missing, the complainant was never
   erased.
4. If the row is present: take a screenshot of the row + the corresponding
   admin booking view (which should show `customer_name = "Anonyme"` and
   `customer_phone = DEL-<prefix>` for every booking). Attach to the CNDP
   response.
5. If the complainant is asking for re-erasure (e.g., they used Ewash
   under a new phone after the first erasure): drive them through the PWA
   delete flow, or run `POST /admin/customers/<new-phone>/erase` directly.

### 5.2 Responding to a customer support ticket

The PWA UI exposes the delete-account flow in
`mobile-app/screens.jsx:1171-1210` (the "Supprimer mon compte" sheet). The
customer should never need an operator to trigger an erasure for them; if
they cannot complete the flow in-app, fall through to the admin-initiated
path under their explicit consent.

### 5.3 Verifying a successful erasure

After running an erasure, the following SQL on production Postgres should
return zero rows:

```sql
SELECT COUNT(*) FROM customer_tokens WHERE customer_phone = '<original-phone>';
SELECT COUNT(*) FROM customer_names WHERE customer_phone = '<original-phone>';
SELECT COUNT(*) FROM customer_vehicles WHERE customer_phone = '<original-phone>';
SELECT COUNT(*) FROM conversation_sessions WHERE customer_phone = '<original-phone>';
SELECT COUNT(*) FROM bookings WHERE customer_phone = '<original-phone>';
```

And exactly one row in:

```sql
SELECT * FROM customers WHERE phone = '<original-phone>';
-- expected: zero rows (renamed to DEL-<hash>)

SELECT * FROM customers WHERE phone LIKE 'DEL-%';
-- expected: at least one row, display_name = 'Anonyme'

SELECT * FROM data_erasure_audit
  WHERE phone_hash = encode(sha256('<original-phone>'::bytea), 'hex')
  ORDER BY performed_at DESC LIMIT 1;
-- expected: exactly one fresh row
```

The end-to-end smoke script `tests/e2e/test_data_erasure.py` automates
this verification against a running backend.

### 5.4 Escalation contacts

- **Engineering on-call:** see `docs/runbooks/pwa-api.md` for the current
  rotation.
- **CNDP correspondence:** legal counsel + operations lead. Contacts kept
  out of this file (no PII in compliance docs); see internal contact
  sheet.
- **Customer support:** WhatsApp staff phone — configured at
  `/admin/notifications`.

---

## 6. Open questions

The items below are intentional gaps in the current implementation. They
should be tracked in `br` and resolved before Ewash goes generally
available.

- **Backup retention window.** Railway Postgres backups are not yet
  enumerated in this doc. If a customer is erased on day N and a backup
  from day N-1 is restored, the original PII reappears. The current
  posture is that Railway's PITR window must be documented and surfaced in
  this doc; see `ewash-6pa.8.11` for the runbook work.
- **Log retention.** API access logs emit `phone_hash` only
  (`app/main.py:64-75`), but Railway's log stream retains those entries
  indefinitely by default. The hash is a one-way function so the log
  stream stays privacy-preserving, but the policy still needs to be
  documented (and the CNDP may want to see an explicit log-retention
  statement).
- **Automated purge of `data_erasure_audit` after 7 years.** No cron job
  exists. At current volume this is a non-issue, but a manual or scheduled
  purge will be needed before the first audit row crosses the boundary
  (i.e., before May 2033).
- **Counsel review of the legal-basis summary.** Section 1 is a working
  summary written by engineering; counsel should confirm the article-number
  citations and adjust the CNDP correspondence protocol before launch.
- **EU resident notification.** The GDPR Article 17 obligation overlaps
  with but is not identical to Loi 09-08. For an EU resident a successful
  erasure should probably also trigger an explicit confirmation email; no
  email channel exists today and the PWA UI's in-app confirmation is the
  only feedback the customer receives.
- **Cross-customer linkage.** If a single human uses two phones, erasing
  one phone does not erase the other. This is intentional (the controller
  cannot know two phones are the same human) but should be documented in
  any customer-facing privacy notice.

---

## References

- Implementation: `app/persistence.py:1647-1782` (`anonymize_customer`),
  `app/api.py:1171-1240` (`DELETE /api/v1/me`),
  `app/admin.py:1039-1073` (admin-initiated erase),
  `app/admin.py:850-895` (`GET /admin/erasures`),
  `app/api_schemas.py:230-249` (request/response schemas + confirm phrase
  constant).
- Schema: `migrations/versions/20260514_0006_pwa_integration.py:128-181`
  (`customer_tokens` + `data_erasure_audit`), `app/models.py:722-750`
  (ORM `DataErasureAuditRow`).
- Tests: `tests/test_api_me_delete.py` (13 in-process compliance tests),
  `tests/e2e/test_data_erasure.py` (live-wire E2E lifecycle).
- Audit checklist: `docs/release-checklists/pwa-integration.md`.
- ADR: `docs/adr/0001-token-scoped-pwa-reads.md` (token model rationale).
- Beads: `ewash-6pa.8.15` (this document), `ewash-6pa.8.14` (E2E script),
  `ewash-6pa.7.19` (the 8-test compliance regression set).
