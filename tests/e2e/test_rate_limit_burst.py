"""E2E: confirm POST /bookings per-phone rate limiting.

This script exercises the production-style booking limit by sending 10 booking
attempts for the same phone and expecting exactly 5 successes followed by 5
HTTP 429 responses with ``Retry-After`` headers.

Standalone:

    python tests/e2e/test_rate_limit_burst.py --base-url https://<railway-domain>

Pytest entrypoint:

    E2E_RUN=1 E2E_BASE_URL=http://localhost:8000 \\
        pytest tests/e2e/test_rate_limit_burst.py

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

LOG = logging.getLogger("e2e.rate_limit_burst")

_DEFAULT_PHONE = "212611200099"
_DEFAULT_ATTEMPTS = 10
_DEFAULT_EXPECTED_SUCCESS = 5


@dataclass
class AttemptResult:
    index: int
    status_code: int
    retry_after: str
    body_preview: str


def _build_payload(phone: str, *, crid: str) -> dict:
    return {
        "phone": phone,
        "name": "E2E Rate Limit User",
        "category": "A",
        "vehicle": {"make": "Dacia Logan", "color": "Blanc"},
        "location": {
            "kind": "home",
            "pin_address": "Rate limit burst test address",
            "address_details": "Gate 3",
        },
        "service_id": "svc_cpl",
        "date": "2026-12-04",
        "slot": "slot_11_13",
        "addon_ids": [],
        "client_request_id": crid,
    }


def _post_attempt(
    client: httpx.Client,
    *,
    index: int,
    phone: str,
) -> AttemptResult:
    response = client.post(
        "/api/v1/bookings",
        json=_build_payload(phone, crid=str(uuid.uuid4())),
    )
    retry_after = response.headers.get("Retry-After", "-")
    result = AttemptResult(
        index=index,
        status_code=response.status_code,
        retry_after=retry_after,
        body_preview=response.text[:240],
    )
    LOG.info(
        "attempt=%d status=%d retry_after=%s",
        result.index,
        result.status_code,
        result.retry_after,
    )
    return result


def _summarize(
    results: list[AttemptResult],
    *,
    expected_successes: int,
    attempts: int,
) -> bool:
    success_count = sum(1 for result in results if result.status_code == 200)
    rate_limited = [result for result in results if result.status_code == 429]
    unexpected = [
        result
        for result in results
        if result.status_code not in {200, 429}
    ]
    LOG.info(
        "=== burst summary: successes=%d rate_limited=%d unexpected=%d ===",
        success_count,
        len(rate_limited),
        len(unexpected),
    )

    ok = True
    if success_count != expected_successes:
        LOG.error("expected %d successes, got %d", expected_successes, success_count)
        ok = False
    expected_limited = attempts - expected_successes
    if len(rate_limited) != expected_limited:
        LOG.error("expected %d 429s, got %d", expected_limited, len(rate_limited))
        ok = False
    missing_retry_after = [
        result.index
        for result in rate_limited
        if result.retry_after == "-"
    ]
    if missing_retry_after:
        LOG.error("429 responses missing Retry-After at attempts=%s", missing_retry_after)
        ok = False
    for result in unexpected:
        LOG.error(
            "unexpected status attempt=%d status=%d body=%s",
            result.index,
            result.status_code,
            result.body_preview,
        )
    if unexpected:
        ok = False

    if ok:
        LOG.info("=== RATE LIMIT BEHAVIOR CONFIRMED ===")
    return ok


def run(
    base_url: str,
    *,
    phone: str = _DEFAULT_PHONE,
    attempts: int = _DEFAULT_ATTEMPTS,
    expected_successes: int = _DEFAULT_EXPECTED_SUCCESS,
    timeout: float = 10.0,
) -> bool:
    """Execute the rate-limit burst E2E against ``base_url``."""
    base_url = base_url.rstrip("/")
    LOG.info(
        "=== START: base_url=%s phone=%s attempts=%d expected_successes=%d ===",
        base_url,
        phone,
        attempts,
        expected_successes,
    )
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        results = [
            _post_attempt(client, index=index, phone=phone)
            for index in range(attempts)
        ]
    return _summarize(
        results,
        expected_successes=expected_successes,
        attempts=attempts,
    )


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True, help="API root, e.g. https://example.com")
    parser.add_argument("--phone", default=os.environ.get("E2E_RATE_LIMIT_PHONE", _DEFAULT_PHONE))
    parser.add_argument("--attempts", type=int, default=_DEFAULT_ATTEMPTS)
    parser.add_argument("--expected-successes", type=int, default=_DEFAULT_EXPECTED_SUCCESS)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)
    return 0 if run(
        args.base_url,
        phone=args.phone,
        attempts=args.attempts,
        expected_successes=args.expected_successes,
        timeout=args.timeout,
    ) else 1


def test_rate_limit_burst_against_live_uvicorn():
    """Opt-in pytest wrapper. Self-skips unless ``E2E_RUN=1``."""
    if os.environ.get("E2E_RUN") != "1":
        pytest.skip("E2E_RUN!=1 - rate limit burst requires a live API")

    base_url = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
    try:
        with httpx.Client(base_url=base_url, timeout=2.0) as client:
            client.get("/health")
    except httpx.HTTPError as exc:
        pytest.skip(f"API not reachable at {base_url}: {exc}")

    if not run(base_url, phone=os.environ.get("E2E_RATE_LIMIT_PHONE", _DEFAULT_PHONE)):
        raise AssertionError("E2E run failed; see captured logs")


if __name__ == "__main__":
    sys.exit(main())
