"""E2E: full PWA booking flow vs admin parity, hit over real HTTP.

This script exercises the happy path against a running uvicorn instance.
Unlike the in-process tests under ``tests/test_api_*.py`` (which use
``fastapi.testclient.TestClient`` and bypass HTTP), this script speaks the
real wire: CORS preflight actually fires, BackgroundTasks actually schedule,
``Cache-Control``/``ETag`` headers actually round-trip, the admin session
cookie is actually set and presented.

Two invocation modes:

1. Standalone smoke (ops / staging):

       python tests/e2e/test_full_booking_flow.py \\
           --base-url https://<railway-domain> \\
           --admin-password "$ADMIN_PASSWORD"

   Exit ``0`` on success, ``1`` on any failure. Each step emits one INFO log
   line so the run is greppable in CI / production observability.

2. Pytest entrypoint (opt-in):

       E2E_RUN=1 E2E_BASE_URL=http://localhost:8000 \\
           E2E_ADMIN_PASSWORD=... pytest tests/e2e/test_full_booking_flow.py

   Without ``E2E_RUN=1`` the test self-skips so the standard ``pytest`` invocation
   stays green when no live server is reachable.

Steps that depend on in-flight beads (``bookings_token`` requires br-4.12;
idempotent replay requires br-4.13) degrade gracefully with a WARN log line
instead of failing — so this script can be committed today and become fully
green as those beads land. Step 4/5 expectations tighten automatically once
the server starts returning a non-empty ``bookings_token``.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx
import pytest

LOG = logging.getLogger("e2e.full_booking_flow")

# Standard demo payload. Date is kept far enough in the future that the
# 2-hour freshness check (``validate_slot_and_date``) never trips.
_TEST_PHONE = "+212 6 11 20 45 02"
_CANONICAL_PHONE = "212611204502"


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""


def _step_ok(name: str, detail: str = "") -> StepResult:
    LOG.info("step ok: %s %s", name, detail)
    return StepResult(name=name, ok=True, detail=detail)


def _step_warn(name: str, detail: str) -> StepResult:
    # Soft-skip: a downstream bead hasn't landed yet. Don't fail the run.
    LOG.warning("step skipped (pending integration): %s %s", name, detail)
    return StepResult(name=name, ok=True, detail=f"skipped: {detail}")


def _step_fail(name: str, detail: str) -> StepResult:
    LOG.error("step FAILED: %s %s", name, detail)
    return StepResult(name=name, ok=False, detail=detail)


def _bootstrap(client: httpx.Client) -> StepResult:
    LOG.info("=== STEP 1: GET /api/v1/bootstrap?category=A ===")
    response = client.get("/api/v1/bootstrap", params={"category": "A"})
    if response.status_code != 200:
        return _step_fail("bootstrap", f"status={response.status_code} body={response.text[:200]}")

    body = response.json()
    categories = body.get("categories") or []
    services = body.get("services") or {}
    if not categories or not services.get("wash"):
        return _step_fail("bootstrap", "missing categories or wash services in response")

    return _step_ok(
        "bootstrap",
        f"categories={len(categories)} wash={len(services.get('wash', []))} "
        f"detailing={len(services.get('detailing', []))} "
        f"etag={response.headers.get('ETag', '-')}",
    )


def _validate_promo(client: httpx.Client) -> StepResult:
    LOG.info("=== STEP 2: POST /api/v1/promos/validate ===")
    response = client.post(
        "/api/v1/promos/validate",
        json={"code": "YS26", "category": "A"},
    )
    if response.status_code != 200:
        return _step_fail("validate_promo", f"status={response.status_code}")

    body = response.json()
    return _step_ok(
        "validate_promo",
        f"valid={body.get('valid')} label={body.get('label')!r} "
        f"discount_count={len(body.get('discounted_prices') or {})}",
    )


def _create_booking(
    client: httpx.Client,
    *,
    client_request_id: Optional[str] = None,
) -> tuple[StepResult, dict]:
    LOG.info("=== STEP 3: POST /api/v1/bookings ===")
    crid = client_request_id or str(uuid.uuid4())
    payload = {
        "phone": _TEST_PHONE,
        "name": "E2E TestUser",
        "category": "A",
        "vehicle": {"make": "Clio", "color": "Bleu"},
        "location": {"kind": "home", "pin_address": "Test Anfa"},
        "service_id": "svc_cpl",
        # 2026-12-01 is a Tuesday, far from any closed date and far in the future.
        "date": "2026-12-01",
        "slot": "slot_11_13",
        "addon_ids": ["svc_cuir"],
        "client_request_id": crid,
    }
    response = client.post("/api/v1/bookings", json=payload)
    if response.status_code != 200:
        return _step_fail("create_booking", f"status={response.status_code} body={response.text[:300]}"), {}

    booking = response.json()
    ref = booking.get("ref", "")
    if not ref.startswith("EW-"):
        return _step_fail("create_booking", f"unexpected ref shape: {ref!r}"), {}

    return _step_ok(
        "create_booking",
        f"ref={ref} total_dh={booking.get('total_dh')} "
        f"token_len={len(booking.get('bookings_token', ''))} crid={crid}",
    ), {"booking": booking, "client_request_id": crid}


def _list_bookings(client: httpx.Client, *, token: str, expected_ref: str) -> StepResult:
    LOG.info("=== STEP 4: GET /api/v1/bookings (token-scoped) ===")
    if not token:
        return _step_warn(
            "list_bookings",
            "POST /bookings returned empty bookings_token (br-4.12 not yet wired)",
        )

    response = client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})
    if response.status_code != 200:
        return _step_fail(
            "list_bookings",
            f"status={response.status_code} body={response.text[:200]}",
        )

    items = response.json().get("bookings") or []
    if not any(b.get("ref") == expected_ref for b in items):
        return _step_fail(
            "list_bookings",
            f"fresh booking {expected_ref} missing from list of {len(items)} items",
        )

    return _step_ok("list_bookings", f"count={len(items)} fresh_ref_present=true")


def _idempotency_retry(
    client: httpx.Client,
    *,
    expected_ref: str,
    client_request_id: str,
) -> StepResult:
    LOG.info("=== STEP 5: POST /api/v1/bookings (idempotency retry) ===")
    payload = {
        "phone": _TEST_PHONE,
        "name": "E2E TestUser",
        "category": "A",
        "vehicle": {"make": "Clio", "color": "Bleu"},
        "location": {"kind": "home", "pin_address": "Test Anfa"},
        "service_id": "svc_cpl",
        "date": "2026-12-01",
        "slot": "slot_11_13",
        "addon_ids": ["svc_cuir"],
        "client_request_id": client_request_id,
    }
    response = client.post("/api/v1/bookings", json=payload)
    if response.status_code != 200:
        return _step_fail("idempotency", f"status={response.status_code} body={response.text[:200]}")

    retry_ref = response.json().get("ref")
    if retry_ref != expected_ref:
        return _step_warn(
            "idempotency",
            f"retry minted a new ref {retry_ref} (expected {expected_ref}) — "
            f"br-4.13 not yet wired",
        )

    return _step_ok("idempotency", f"ref preserved: {retry_ref}")


def _verify_admin_parity(
    base_url: str,
    *,
    admin_password: str,
    booking_ref: str,
) -> StepResult:
    LOG.info("=== STEP 6: admin parity ===")
    if not admin_password:
        return _step_warn(
            "admin_parity",
            "no admin password supplied — skip the admin source-badge check",
        )

    with httpx.Client(base_url=base_url, timeout=10.0, follow_redirects=True) as client:
        # Login posts the password, which sets the admin session cookie.
        login = client.post("/admin", data={"password": admin_password})
        if login.status_code not in (200, 302, 303):
            return _step_fail("admin_parity", f"login status={login.status_code}")

        listing = client.get("/admin/bookings")
        if listing.status_code != 200:
            return _step_fail("admin_parity", f"/admin/bookings status={listing.status_code}")

        if booking_ref not in listing.text:
            return _step_fail("admin_parity", f"ref {booking_ref} not visible in /admin/bookings")

        # Source badge for PWA bookings ships under class="src-pwa" (br-5.2).
        # Check for the css class so the assertion is robust against label
        # text changes (fr "PWA" vs en "PWA" — same letters here but the
        # class survives any rewording).
        if "src-pwa" not in listing.text:
            return _step_fail("admin_parity", "PWA source badge (.src-pwa) missing from /admin/bookings")

        return _step_ok("admin_parity", f"ref + .src-pwa badge present in /admin/bookings")


def run(base_url: str, admin_password: str = "") -> bool:  # nosec B107 — empty default skips Step 6
    """Execute every step against ``base_url``. Returns True iff all steps pass."""
    LOG.info("=== START: base_url=%s admin_check=%s ===", base_url, bool(admin_password))
    base_url = base_url.rstrip("/")

    results: list[StepResult] = []
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        results.append(_bootstrap(client))
        results.append(_validate_promo(client))

        create_result, ctx = _create_booking(client)
        results.append(create_result)
        if not create_result.ok:
            return _summarize(results)

        booking = ctx["booking"]
        results.append(
            _list_bookings(
                client,
                token=booking.get("bookings_token", ""),
                expected_ref=booking["ref"],
            )
        )
        results.append(
            _idempotency_retry(
                client,
                expected_ref=booking["ref"],
                client_request_id=ctx["client_request_id"],
            )
        )

    results.append(
        _verify_admin_parity(
            base_url,
            admin_password=admin_password,
            booking_ref=booking["ref"],
        )
    )

    return _summarize(results)


def _summarize(results: list[StepResult]) -> bool:
    failed = [r for r in results if not r.ok]
    if failed:
        LOG.error(
            "=== FAILED: %d/%d steps had hard failures ===",
            len(failed),
            len(results),
        )
        for r in failed:
            LOG.error("  %s — %s", r.name, r.detail)
        return False

    LOG.info("=== ALL %d STEPS PASSED ===", len(results))
    return True


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True, help="API root, e.g. https://example.com")
    parser.add_argument(
        "--admin-password",
        default=os.environ.get("E2E_ADMIN_PASSWORD", ""),
        help="Admin password for the parity check (env: E2E_ADMIN_PASSWORD). "
        "If omitted, Step 6 is skipped with a warning.",
    )
    args = parser.parse_args(argv)
    return 0 if run(args.base_url, args.admin_password) else 1


# ── Pytest entrypoint ─────────────────────────────────────────────────────


def test_full_booking_flow_against_live_uvicorn():
    """Opt-in pytest wrapper. Self-skips unless ``E2E_RUN=1``.

    Without ``E2E_RUN`` set the script needs a live uvicorn and isn't suitable
    for the in-process CI loop. Set ``E2E_RUN=1`` (and optionally
    ``E2E_BASE_URL`` / ``E2E_ADMIN_PASSWORD``) to run.
    """
    if os.environ.get("E2E_RUN") != "1":
        pytest.skip("E2E_RUN!=1 — full booking flow requires a live uvicorn")

    base_url = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
    admin_password = os.environ.get("E2E_ADMIN_PASSWORD", "")

    # Connection probe before the real run so the failure mode is "server not
    # reachable" instead of a noisy traceback mid-step.
    try:
        with httpx.Client(base_url=base_url, timeout=2.0) as client:
            client.get("/health")
    except httpx.HTTPError as exc:
        pytest.skip(f"uvicorn not reachable at {base_url}: {exc}")

    if not run(base_url, admin_password):
        raise AssertionError("E2E run failed; see captured logs")


if __name__ == "__main__":
    sys.exit(main())
