"""E2E: verify PWA booking + WhatsApp inbound dedupe to one customer.

The automated part creates a PWA-style booking, then posts a Meta-style signed
WhatsApp webhook message from the same normalized phone number. The final
customer-table and WhatsApp-response checks remain operator-confirmed because
production exposes no hardened E2E-only customer lookup endpoint.

Standalone:

    python tests/e2e/test_cross_channel_dedup.py \\
        --base-url https://<railway-domain> \\
        --meta-app-secret "$META_APP_SECRET"

Pytest entrypoint:

    E2E_RUN=1 E2E_BASE_URL=http://localhost:8000 META_APP_SECRET=... \\
        pytest tests/e2e/test_cross_channel_dedup.py

Without ``E2E_RUN=1`` the pytest wrapper self-skips so normal test runs do not
need a live uvicorn process or Meta secret.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx
import pytest

LOG = logging.getLogger("e2e.cross_channel_dedup")

_TEST_PHONE_PWA = "+212 6 11 20 88 99"
_TEST_PHONE_NORM = "212611208899"


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


def _booking_payload(*, crid: str) -> dict:
    return {
        "phone": _TEST_PHONE_PWA,
        "name": "DedupTest",
        "category": "A",
        "vehicle": {"make": "Sentra", "color": "Jaune"},
        "location": {
            "kind": "home",
            "pin_address": "Test Casablanca",
            "address_details": "E2E cross-channel dedup",
        },
        "service_id": "svc_ext",
        "date": "2026-12-15",
        "slot": "slot_14_16",
        "addon_ids": [],
        "client_request_id": crid,
    }


def _webhook_payload(*, message_id: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "test",
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": _TEST_PHONE_NORM,
                                    "id": message_id,
                                    "timestamp": "1747000000",
                                    "type": "text",
                                    "text": {"body": "Bonjour"},
                                }
                            ],
                            "contacts": [
                                {
                                    "wa_id": _TEST_PHONE_NORM,
                                    "profile": {"name": "DedupTest WA"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _signed_webhook_body(meta_app_secret: str, payload: dict) -> tuple[bytes, str]:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(
        meta_app_secret.encode("utf-8"),
        raw,
        hashlib.sha256,
    ).hexdigest()
    return raw, f"sha256={digest}"


def _post_pwa_booking(client: httpx.Client) -> tuple[StepResult, dict]:
    LOG.info("=== STEP 1: POST a booking from PWA-style payload ===")
    response = client.post(
        "/api/v1/bookings",
        json=_booking_payload(crid=str(uuid.uuid4())),
    )
    if response.status_code != 200:
        return _step_fail("pwa_booking", f"status={response.status_code} body={response.text[:300]}"), {}

    body = response.json()
    ref = body.get("ref", "")
    if not ref.startswith("EW-"):
        return _step_fail("pwa_booking", f"unexpected ref={ref!r}"), body
    LOG.info("PWA booking created ref=%s", ref)
    return _step_ok("pwa_booking", f"ref={ref}"), body


def _post_signed_webhook(
    client: httpx.Client,
    *,
    meta_app_secret: str,
) -> StepResult:
    LOG.info("=== STEP 2: simulate a WhatsApp inbound from the same normalized phone ===")
    payload = _webhook_payload(message_id="wamid.test_" + uuid.uuid4().hex)
    raw, signature = _signed_webhook_body(meta_app_secret, payload)
    response = client.post(
        "/webhook",
        content=raw,
        headers={
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json",
        },
    )
    if response.status_code != 200:
        return _step_fail("signed_webhook", f"status={response.status_code} body={response.text[:300]}")
    return _step_ok("signed_webhook", "Meta-style HMAC accepted")


def _manual_customer_check() -> StepResult:
    LOG.info("=== STEP 3: verify customer row count ===")
    LOG.info(
        "Manual check: /admin/customers should show ONE row for phone %s with both names accumulated",
        _TEST_PHONE_NORM,
    )
    return _step_ok("manual_customer_check", f"phone={_TEST_PHONE_NORM}")


def _manual_whatsapp_check() -> StepResult:
    LOG.info("=== STEP 4: verify returning-customer prompt was sent ===")
    LOG.info(
        "Manual check: the WhatsApp test number should receive the returning-customer prompt for Sentra - Jaune",
    )
    return _step_ok("manual_whatsapp_check", "operator confirmation required")


def _summarize(results: list[StepResult]) -> bool:
    failed = [result for result in results if not result.ok]
    if failed:
        LOG.error("=== FAILED: %d/%d cross-channel steps failed ===", len(failed), len(results))
        for result in failed:
            LOG.error("  %s - %s", result.name, result.detail)
        return False
    LOG.info("=== DEDUP STEPS COMPLETED - OPERATOR CONFIRMS MANUAL CHECKS ===")
    return True


def run(base_url: str, *, meta_app_secret: str, timeout: float = 10.0) -> bool:
    """Execute the cross-channel dedup E2E against ``base_url``."""
    base_url = base_url.rstrip("/")
    LOG.info("=== START: base_url=%s phone=%s ===", base_url, _TEST_PHONE_NORM)
    results: list[StepResult] = []
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        result, _booking = _post_pwa_booking(client)
        results.append(result)
        if not result.ok:
            return _summarize(results)
        results.append(_post_signed_webhook(client, meta_app_secret=meta_app_secret))
    results.append(_manual_customer_check())
    results.append(_manual_whatsapp_check())
    return _summarize(results)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True, help="API root, e.g. https://example.com")
    parser.add_argument("--meta-app-secret", default=os.environ.get("META_APP_SECRET"))
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)
    if not args.meta_app_secret:
        parser.error("--meta-app-secret or META_APP_SECRET is required")
    return 0 if run(
        args.base_url,
        meta_app_secret=args.meta_app_secret,
        timeout=args.timeout,
    ) else 1


def test_cross_channel_dedup_against_live_uvicorn():
    """Opt-in pytest wrapper. Self-skips unless ``E2E_RUN=1``."""
    if os.environ.get("E2E_RUN") != "1":
        pytest.skip("E2E_RUN!=1 - cross-channel dedup requires a live API")

    meta_app_secret = os.environ.get("META_APP_SECRET")
    if not meta_app_secret:
        pytest.skip("META_APP_SECRET missing; cannot sign webhook payload")

    base_url = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
    try:
        with httpx.Client(base_url=base_url, timeout=2.0) as client:
            client.get("/health")
    except httpx.HTTPError as exc:
        pytest.skip(f"API not reachable at {base_url}: {exc}")

    if not run(base_url, meta_app_secret=meta_app_secret):
        raise AssertionError("E2E run failed; see captured logs")


if __name__ == "__main__":
    sys.exit(main())
