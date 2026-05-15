"""E2E: token mint, reuse, and fresh-mint-on-mismatch.

This script exercises customer booking-token behavior against a running API:

1. First booking sends no token and receives a fresh ``bookings_token``.
2. Second booking sends that token and receives the same token back.
3. Third booking sends a bogus token and receives a fresh token.
4. The original token still lists the customer's bookings after the fresh mint.

Standalone:

    python tests/e2e/test_token_lifecycle.py --base-url https://<railway-domain>

Pytest entrypoint:

    E2E_RUN=1 E2E_BASE_URL=http://localhost:8000 \\
        pytest tests/e2e/test_token_lifecycle.py

Without ``E2E_RUN=1`` the pytest wrapper self-skips so normal test runs do not
need a live uvicorn process.
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

LOG = logging.getLogger("e2e.token_lifecycle")

_TEST_PHONE = "212611200001"
_BOGUS_TOKEN = "not-a-real-token-12345"


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""


def _step_ok(name: str, detail: str = "") -> StepResult:
    LOG.info("step ok: %s %s", name, detail)
    return StepResult(name=name, ok=True, detail=detail)


def _step_fail(name: str, detail: str) -> StepResult:
    LOG.error("step FAILED: %s %s", name, detail)
    return StepResult(name=name, ok=False, detail=detail)


def _build_payload(
    phone: str,
    *,
    crid: str,
    bookings_token: str | None = None,
    date: str = "2026-12-02",
) -> dict:
    payload = {
        "phone": phone,
        "name": "E2E Token User",
        "category": "A",
        "vehicle": {"make": "Dacia Logan", "color": "Bleu"},
        "location": {
            "kind": "home",
            "pin_address": "Token lifecycle test address",
            "address_details": "Gate 3",
        },
        "service_id": "svc_cpl",
        "date": date,
        "slot": "slot_11_13",
        "addon_ids": [],
        "client_request_id": crid,
    }
    if bookings_token is not None:
        payload["bookings_token"] = bookings_token
    return payload


def _post_booking(
    client: httpx.Client,
    *,
    step_name: str,
    payload: dict,
) -> tuple[StepResult, dict]:
    response = client.post("/api/v1/bookings", json=payload)
    if response.status_code != 200:
        return (
            _step_fail(
                step_name,
                f"status={response.status_code} body={response.text[:300]}",
            ),
            {},
        )

    body = response.json()
    ref = body.get("ref", "")
    token = body.get("bookings_token", "")
    if not ref.startswith("EW-"):
        return _step_fail(step_name, f"unexpected ref={ref!r}"), {}
    if not token:
        return _step_fail(step_name, f"empty bookings_token ref={ref}"), {}
    return _step_ok(step_name, f"ref={ref} token_len={len(token)}"), body


def _booking_one_mints_token(client: httpx.Client) -> tuple[StepResult, dict]:
    LOG.info("=== STEP 1: Booking 1 without token mints fresh token ===")
    return _post_booking(
        client,
        step_name="booking_1_mint",
        payload=_build_payload(_TEST_PHONE, crid=str(uuid.uuid4())),
    )


def _booking_two_reuses_token(
    client: httpx.Client,
    *,
    token_1: str,
) -> tuple[StepResult, dict]:
    LOG.info("=== STEP 2: Booking 2 with token_1 echoes same token ===")
    result, body = _post_booking(
        client,
        step_name="booking_2_reuse",
        payload=_build_payload(
            _TEST_PHONE,
            crid=str(uuid.uuid4()),
            bookings_token=token_1,
        ),
    )
    if not result.ok:
        return result, body
    token_2 = body.get("bookings_token")
    if token_2 != token_1:
        return _step_fail("booking_2_reuse", "server returned a different token"), body
    return _step_ok("booking_2_reuse", f"ref={body.get('ref')} token_reused=true"), body


def _booking_three_mints_on_bogus_token(
    client: httpx.Client,
    *,
    token_1: str,
) -> tuple[StepResult, dict]:
    LOG.info("=== STEP 3: Booking 3 with bogus token mints fresh token ===")
    result, body = _post_booking(
        client,
        step_name="booking_3_bogus",
        payload=_build_payload(
            _TEST_PHONE,
            crid=str(uuid.uuid4()),
            bookings_token=_BOGUS_TOKEN,
        ),
    )
    if not result.ok:
        return result, body
    token_3 = body.get("bookings_token")
    if token_3 in {token_1, _BOGUS_TOKEN}:
        return (
            _step_fail(
                "booking_3_bogus",
                "server did not mint a fresh replacement token",
            ),
            body,
        )
    return _step_ok("booking_3_bogus", f"ref={body.get('ref')} fresh_token=true"), body


def _old_token_still_lists_bookings(
    client: httpx.Client,
    *,
    token_1: str,
    expected_refs: set[str],
) -> StepResult:
    LOG.info("=== STEP 4: GET /bookings with token_1 remains valid ===")
    response = client.get("/api/v1/bookings", headers={"X-Ewash-Token": token_1})
    if response.status_code != 200:
        return _step_fail(
            "old_token_list",
            f"status={response.status_code} body={response.text[:300]}",
        )

    bookings = response.json().get("bookings") or []
    returned_refs = {item.get("ref") for item in bookings}
    missing = sorted(ref for ref in expected_refs if ref not in returned_refs)
    if missing:
        return _step_fail(
            "old_token_list",
            f"missing_refs={missing} returned_count={len(bookings)}",
        )

    return _step_ok(
        "old_token_list",
        f"count={len(bookings)} refs_present={len(expected_refs)}",
    )


def _summarize(results: list[StepResult]) -> bool:
    failed = [result for result in results if not result.ok]
    if failed:
        LOG.error(
            "=== FAILED: %d/%d token lifecycle steps failed ===",
            len(failed),
            len(results),
        )
        for result in failed:
            LOG.error("  %s - %s", result.name, result.detail)
        return False

    LOG.info("=== ALL %d TOKEN LIFECYCLE STEPS PASSED ===", len(results))
    return True


def run(base_url: str) -> bool:
    """Execute the token lifecycle E2E against ``base_url``."""
    base_url = base_url.rstrip("/")
    LOG.info("=== START: base_url=%s phone=%s ===", base_url, _TEST_PHONE)

    results: list[StepResult] = []
    expected_refs: set[str] = set()

    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        result_1, booking_1 = _booking_one_mints_token(client)
        results.append(result_1)
        if not result_1.ok:
            return _summarize(results)
        token_1 = booking_1["bookings_token"]
        expected_refs.add(booking_1["ref"])

        result_2, booking_2 = _booking_two_reuses_token(client, token_1=token_1)
        results.append(result_2)
        if not result_2.ok:
            return _summarize(results)
        expected_refs.add(booking_2["ref"])

        result_3, booking_3 = _booking_three_mints_on_bogus_token(
            client,
            token_1=token_1,
        )
        results.append(result_3)
        if not result_3.ok:
            return _summarize(results)
        expected_refs.add(booking_3["ref"])

        results.append(
            _old_token_still_lists_bookings(
                client,
                token_1=token_1,
                expected_refs=expected_refs,
            )
        )

    return _summarize(results)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True, help="API root, e.g. https://example.com")
    args = parser.parse_args(argv)
    return 0 if run(args.base_url) else 1


def test_token_lifecycle_against_live_uvicorn():
    """Opt-in pytest wrapper. Self-skips unless ``E2E_RUN=1``."""
    if os.environ.get("E2E_RUN") != "1":
        pytest.skip("E2E_RUN!=1 - token lifecycle requires a live uvicorn")

    base_url = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
    try:
        with httpx.Client(base_url=base_url, timeout=2.0) as client:
            client.get("/health")
    except httpx.HTTPError as exc:
        pytest.skip(f"uvicorn not reachable at {base_url}: {exc}")

    if not run(base_url):
        raise AssertionError("E2E run failed; see captured logs")


if __name__ == "__main__":
    sys.exit(main())
