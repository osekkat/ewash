"""E2E: customer self-serve data erasure (DELETE /api/v1/me) lifecycle.

This script exercises the Loi 09-08 / GDPR right-to-erasure path against a
running backend. Unlike the in-process tests under
``tests/test_api_me_delete.py`` (which use ``fastapi.testclient.TestClient``
and bypass HTTP), this script speaks the real wire: every step is an actual
HTTPS request, the token is minted server-side at first booking, and the
erasure has to physically revoke that token across requests.

Steps (5 hard, 1 best-effort):

1. POST ``/api/v1/bookings`` with a clean test phone → mint ``bookings_token``.
2. POST a second booking with the same token → expect 200 + same token echoed.
3. GET ``/api/v1/bookings`` with the token → expect 200 + non-empty list.
4. DELETE ``/api/v1/me`` with the literal confirm phrase + the token → expect
   200 with ``deleted_count >= 1`` and ``anonymized_bookings >= 2``.
5. GET ``/api/v1/bookings`` with the same (now-deleted) token → expect 401
   with ``error_code == "invalid_token"``.
6. POST ``/api/v1/tokens/revoke`` with the same token → expect 401 (defensive
   check: the token was wiped, every authenticated route should agree).

Standalone smoke (defaults to localhost):

    python tests/e2e/test_data_erasure.py
    python tests/e2e/test_data_erasure.py --base-url https://<railway-domain>
    python tests/e2e/test_data_erasure.py --keep-data   # dry-run, no DELETE

Pytest entrypoint (opt-in):

    E2E_RUN=1 E2E_BASE_URL=http://localhost:8000 \\
        pytest tests/e2e/test_data_erasure.py

Without ``E2E_RUN=1`` the pytest wrapper self-skips so the standard
``pytest`` invocation stays green when no live server is reachable.

``--keep-data`` (or ``E2E_KEEP_DATA=1``) leaves the test customer in place;
useful when probing against a shared staging backend where wiping the row is
undesirable. In keep-data mode steps 4-6 self-skip with a WARN log line.
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

LOG = logging.getLogger("e2e.data_erasure")

# Test phone is deliberately E.164 with the country code spelled out so the
# server's normalization is a no-op — the wire payload and the server's stored
# value match byte-for-byte, which keeps the eventual phone_hash deterministic.
_TEST_PHONE = "212611204502"
_CONFIRM_PHRASE = "I confirm I want to delete my data"


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""


def _step_ok(name: str, detail: str = "") -> StepResult:
    LOG.info("step ok: %s %s", name, detail)
    return StepResult(name=name, ok=True, detail=detail)


def _step_warn(name: str, detail: str) -> StepResult:
    # Soft-skip: --keep-data mode short-circuits the destructive steps.
    LOG.warning("step skipped: %s %s", name, detail)
    return StepResult(name=name, ok=True, detail=f"skipped: {detail}")


def _step_fail(name: str, detail: str) -> StepResult:
    LOG.error("step FAILED: %s %s", name, detail)
    return StepResult(name=name, ok=False, detail=detail)


def _build_payload(
    phone: str,
    *,
    crid: str,
    bookings_token: str | None = None,
    date: str = "2026-12-03",
) -> dict:
    payload = {
        "phone": phone,
        "name": "E2E Erasure User",
        "category": "A",
        "vehicle": {"make": "Dacia Sandero", "color": "Rouge"},
        "location": {
            "kind": "home",
            "pin_address": "Data erasure test address",
            "address_details": "Gate 7",
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


def _step_1_first_booking_mints_token(
    client: httpx.Client,
) -> tuple[StepResult, dict]:
    LOG.info("=== STEP 1: First booking mints fresh bookings_token ===")
    return _post_booking(
        client,
        step_name="booking_1_mint",
        payload=_build_payload(_TEST_PHONE, crid=str(uuid.uuid4())),
    )


def _step_2_second_booking_reuses_token(
    client: httpx.Client,
    *,
    token: str,
) -> tuple[StepResult, dict]:
    LOG.info("=== STEP 2: Second booking with same token echoes the token ===")
    result, body = _post_booking(
        client,
        step_name="booking_2_history",
        payload=_build_payload(
            _TEST_PHONE,
            crid=str(uuid.uuid4()),
            bookings_token=token,
            date="2026-12-04",
        ),
    )
    if not result.ok:
        return result, body
    echoed = body.get("bookings_token")
    if echoed != token:
        return (
            _step_fail(
                "booking_2_history",
                f"server returned a different token (expected echo of token_1)",
            ),
            body,
        )
    return _step_ok(
        "booking_2_history",
        f"ref={body.get('ref')} token_reused=true",
    ), body


def _step_3_list_returns_history(
    client: httpx.Client,
    *,
    token: str,
    expected_refs: set[str],
) -> StepResult:
    LOG.info("=== STEP 3: GET /api/v1/bookings with token returns history ===")
    response = client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})
    if response.status_code != 200:
        return _step_fail(
            "list_before_delete",
            f"status={response.status_code} body={response.text[:300]}",
        )

    bookings = response.json().get("bookings") or []
    returned_refs = {item.get("ref") for item in bookings}
    missing = sorted(ref for ref in expected_refs if ref not in returned_refs)
    if missing:
        return _step_fail(
            "list_before_delete",
            f"missing_refs={missing} returned_count={len(bookings)}",
        )

    return _step_ok(
        "list_before_delete",
        f"count={len(bookings)} refs_present={len(expected_refs)}",
    )


def _step_4_delete_me(
    client: httpx.Client,
    *,
    token: str,
    expected_min_anonymized: int,
) -> StepResult:
    LOG.info("=== STEP 4: DELETE /api/v1/me with confirm phrase + token ===")
    response = client.request(
        "DELETE",
        "/api/v1/me",
        json={"confirm": _CONFIRM_PHRASE},
        headers={"X-Ewash-Token": token},
    )
    # The handler returns 200 on success per `app/api.py` (MeDeleteResponse
    # body); a 204 would also be a reasonable contract so accept either.
    if response.status_code not in (200, 204):
        return _step_fail(
            "delete_me",
            f"status={response.status_code} body={response.text[:300]}",
        )

    if response.status_code == 204:
        return _step_ok("delete_me", "status=204 no_content")

    body = response.json()
    deleted_count = body.get("deleted_count")
    anonymized_bookings = body.get("anonymized_bookings")
    if not isinstance(deleted_count, int) or deleted_count < 1:
        return _step_fail(
            "delete_me",
            f"unexpected deleted_count={deleted_count!r} body={body}",
        )
    if (
        not isinstance(anonymized_bookings, int)
        or anonymized_bookings < expected_min_anonymized
    ):
        return _step_fail(
            "delete_me",
            f"expected anonymized_bookings>={expected_min_anonymized} "
            f"got {anonymized_bookings!r} body={body}",
        )
    return _step_ok(
        "delete_me",
        f"deleted_count={deleted_count} "
        f"anonymized_bookings={anonymized_bookings}",
    )


def _step_5_list_after_delete_is_unauthorized(
    client: httpx.Client,
    *,
    token: str,
) -> StepResult:
    LOG.info("=== STEP 5: GET /api/v1/bookings with revoked token → 401 ===")
    response = client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})
    if response.status_code != 401:
        return _step_fail(
            "list_after_delete",
            f"expected 401 got status={response.status_code} body={response.text[:300]}",
        )

    error_code = ""
    try:
        error_code = response.json().get("error_code", "")
    except ValueError:
        # Non-JSON body — surface the raw text so the operator can diagnose.
        return _step_fail(
            "list_after_delete",
            f"401 with non-JSON body: {response.text[:200]!r}",
        )
    if error_code != "invalid_token":
        return _step_fail(
            "list_after_delete",
            f"expected error_code=invalid_token got {error_code!r}",
        )
    return _step_ok(
        "list_after_delete",
        f"status=401 error_code={error_code}",
    )


def _step_6_revoke_after_delete_is_unauthorized(
    client: httpx.Client,
    *,
    token: str,
) -> StepResult:
    LOG.info("=== STEP 6: POST /api/v1/tokens/revoke with revoked token → 401 ===")
    response = client.post(
        "/api/v1/tokens/revoke",
        json={"scope": "current"},
        headers={"X-Ewash-Token": token},
    )
    if response.status_code != 401:
        return _step_fail(
            "revoke_after_delete",
            f"expected 401 got status={response.status_code} body={response.text[:300]}",
        )
    try:
        error_code = response.json().get("error_code", "")
    except ValueError:
        return _step_fail(
            "revoke_after_delete",
            f"401 with non-JSON body: {response.text[:200]!r}",
        )
    if error_code != "invalid_token":
        return _step_fail(
            "revoke_after_delete",
            f"expected error_code=invalid_token got {error_code!r}",
        )
    return _step_ok(
        "revoke_after_delete",
        f"status=401 error_code={error_code}",
    )


def _summarize(results: list[StepResult]) -> bool:
    failed = [result for result in results if not result.ok]
    if failed:
        LOG.error(
            "=== FAILED: %d/%d data erasure steps failed ===",
            len(failed),
            len(results),
        )
        for result in failed:
            LOG.error("  %s - %s", result.name, result.detail)
        return False

    LOG.info("=== ALL %d DATA ERASURE STEPS PASSED ===", len(results))
    return True


def run(base_url: str, *, keep_data: bool = False) -> bool:
    """Execute the data erasure E2E against ``base_url``.

    With ``keep_data=True`` the destructive DELETE step is skipped, leaving
    the bookings + token intact. Useful for probing a shared backend where
    wiping rows is undesirable.
    """
    base_url = base_url.rstrip("/")
    LOG.info(
        "=== START: base_url=%s phone=%s keep_data=%s ===",
        base_url,
        _TEST_PHONE,
        keep_data,
    )

    results: list[StepResult] = []
    expected_refs: set[str] = set()

    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        result_1, booking_1 = _step_1_first_booking_mints_token(client)
        results.append(result_1)
        if not result_1.ok:
            return _summarize(results)
        token = booking_1["bookings_token"]
        expected_refs.add(booking_1["ref"])

        result_2, booking_2 = _step_2_second_booking_reuses_token(
            client,
            token=token,
        )
        results.append(result_2)
        if not result_2.ok:
            return _summarize(results)
        expected_refs.add(booking_2["ref"])

        results.append(
            _step_3_list_returns_history(
                client,
                token=token,
                expected_refs=expected_refs,
            )
        )

        if keep_data:
            results.append(
                _step_warn(
                    "delete_me",
                    "--keep-data: skipped destructive DELETE /api/v1/me",
                )
            )
            results.append(
                _step_warn(
                    "list_after_delete",
                    "--keep-data: skipped post-delete 401 assertion",
                )
            )
            results.append(
                _step_warn(
                    "revoke_after_delete",
                    "--keep-data: skipped post-delete revoke 401 assertion",
                )
            )
            return _summarize(results)

        result_4 = _step_4_delete_me(
            client,
            token=token,
            expected_min_anonymized=len(expected_refs),
        )
        results.append(result_4)
        if not result_4.ok:
            return _summarize(results)

        results.append(
            _step_5_list_after_delete_is_unauthorized(client, token=token)
        )
        results.append(
            _step_6_revoke_after_delete_is_unauthorized(client, token=token)
        )

    return _summarize(results)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base-url",
        default=os.environ.get("E2E_BASE_URL", "http://localhost:8000"),
        help="API root (env: E2E_BASE_URL, default: http://localhost:8000)",
    )
    parser.add_argument(
        "--keep-data",
        action="store_true",
        default=os.environ.get("E2E_KEEP_DATA") == "1",
        help="Dry-run: skip the destructive DELETE step (env: E2E_KEEP_DATA=1)",
    )
    args = parser.parse_args(argv)
    return 0 if run(args.base_url, keep_data=args.keep_data) else 1


def test_data_erasure_against_live_uvicorn():
    """Opt-in pytest wrapper. Self-skips unless ``E2E_RUN=1``."""
    if os.environ.get("E2E_RUN") != "1":
        pytest.skip("E2E_RUN!=1 - data erasure requires a live uvicorn")

    base_url = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
    keep_data = os.environ.get("E2E_KEEP_DATA") == "1"
    try:
        with httpx.Client(base_url=base_url, timeout=2.0) as client:
            client.get("/health")
    except httpx.HTTPError as exc:
        pytest.skip(f"uvicorn not reachable at {base_url}: {exc}")

    if not run(base_url, keep_data=keep_data):
        raise AssertionError("E2E run failed; see captured logs")


if __name__ == "__main__":
    sys.exit(main())
