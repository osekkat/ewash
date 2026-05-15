"""Load test: concurrent POST /bookings race-safety properties.

Run the in-process load tests with:

    pytest -m load tests/load/test_concurrent_bookings.py -v

Run against a live instance with:

    python tests/load/test_concurrent_bookings.py --base-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import concurrent.futures
import logging
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_REQUIRED_ENV_DEFAULTS = {
    "META_APP_SECRET": "ewash-load-meta-app",
    "META_VERIFY_TOKEN": "ewash-load-meta-verify",
    "META_ACCESS_TOKEN": "ewash-load-meta-access",
    "META_PHONE_NUMBER_ID": "ewash-load-meta-phone",
    "ADMIN_PASSWORD": "ewash-load-admin",
    "INTERNAL_CRON_SECRET": "ewash-load-cron",
}
for _env_name, _env_value in _REQUIRED_ENV_DEFAULTS.items():
    os.environ.setdefault(_env_name, _env_value)

from app import api, catalog, notifications, persistence
from app.config import settings
from app.db import init_db, make_engine, session_scope
from app.models import BookingRefCounterRow, BookingRow
from app.rate_limit import limiter, rate_limit_exceeded_handler

LOG = logging.getLogger("load.concurrent_bookings")
pytestmark = pytest.mark.load


@dataclass
class PostResult:
    status_code: int
    body: dict
    headers: dict[str, str]
    text: str = ""


PostFunc = Callable[[dict], PostResult]


def _payload(
    *,
    phone: str,
    crid: str,
    name: str = "LoadTest",
) -> dict:
    return {
        "phone": phone,
        "name": name,
        "category": "A",
        "vehicle": {"make": "Clio", "color": "Bleu"},
        "location": {"kind": "home", "pin_address": "Load Test"},
        "service_id": "svc_ext",
        "date": "2026-12-01",
        "slot": "slot_11_13",
        "addon_ids": [],
        "client_request_id": crid,
    }


def _client() -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.include_router(api.router)
    api.install_exception_handlers(app)
    return TestClient(app)


def _testclient_post(payload: dict) -> PostResult:
    with _client() as client:
        response = client.post("/api/v1/bookings", json=payload)
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text}
        return PostResult(
            status_code=response.status_code,
            body=body,
            headers=dict(response.headers),
            text=response.text,
        )


def _httpx_post(base_url: str, payload: dict) -> PostResult:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=15.0) as client:
        response = client.post("/api/v1/bookings", json=payload)
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text}
        return PostResult(
            status_code=response.status_code,
            body=body,
            headers=dict(response.headers),
            text=response.text,
        )


def _booking_count(engine) -> int:
    with session_scope(engine) as session:
        return session.scalar(select(func.count()).select_from(BookingRow)) or 0


def _ref_counter_value(engine) -> int:
    with session_scope(engine) as session:
        return session.scalar(
            select(BookingRefCounterRow.last_counter)
        ) or 0


@pytest.fixture
def load_db(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'load-bookings.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(settings, "rate_limit_bookings_per_phone", "1000/hour")
    monkeypatch.setattr(settings, "rate_limit_bookings_per_ip", "1000/hour")
    persistence._configured_engine.cache_clear()
    catalog.catalog_cache_clear()
    notifications.notification_cache_clear()
    limiter.reset()

    async def noop_staff_alert(*_args, **_kwargs):
        return None

    monkeypatch.setattr(notifications, "notify_booking_confirmation_safe", noop_staff_alert)
    try:
        yield engine
    finally:
        persistence._configured_engine.cache_clear()
        catalog.catalog_cache_clear()
        notifications.notification_cache_clear()
        limiter.reset()


def run_distinct_refs(post: PostFunc, *, n: int = 50, max_workers: int = 20) -> list[str]:
    """N concurrent distinct phones -> N distinct refs, no errors."""
    LOG.info("=== distinct refs: firing %d concurrent POSTs ===", n)
    payloads = [
        _payload(
            phone=f"21261120{index:04d}",
            crid=str(uuid.uuid4()),
            name=f"LoadTest{index}",
        )
        for index in range(n)
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(post, payloads))

    successes = [result for result in results if result.status_code == 200]
    refs = [result.body.get("ref") for result in successes]
    LOG.info("got %d successes / %d", len(successes), n)
    assert len(successes) == n, f"only {len(successes)}/{n} successful: {results}"
    assert len(set(refs)) == n, f"ref collision: {len(set(refs))} unique out of {n}"
    LOG.info("=== all %d refs distinct ===", n)
    return refs


def run_idempotency_under_contention(
    post: PostFunc,
    *,
    seed_first: bool = False,
    attempts: int = 10,
) -> list[str]:
    """Concurrent same-crid retries -> every success returns one ref."""
    LOG.info("=== idempotency contention: %d concurrent POSTs same crid ===", attempts)
    payload = _payload(
        phone="212611299988",
        crid=str(uuid.uuid4()),
        name="ContentionTest",
    )
    if seed_first:
        seeded = post(payload)
        assert seeded.status_code == 200, seeded
        expected_ref = seeded.body.get("ref")
    else:
        expected_ref = None

    with concurrent.futures.ThreadPoolExecutor(max_workers=attempts) as executor:
        results = list(executor.map(lambda _index: post(payload), range(attempts)))

    successes = [result for result in results if result.status_code == 200]
    refs = [result.body.get("ref") for result in successes]
    assert len(successes) == attempts, f"some failed: {results}"
    assert all(ref is not None for ref in refs), refs
    assert len(set(refs)) == 1, f"idempotency broken: {set(refs)}"
    if expected_ref is not None:
        assert refs[0] == expected_ref
    LOG.info("=== all %d returned same ref: %s ===", attempts, refs[0])
    return refs


def run_rate_limit_burst(post: PostFunc, *, n: int = 50) -> dict[int, int]:
    """N POSTs from one phone -> mix of 200 + 429 once phone cap is consumed."""
    LOG.info("=== rate limit burst: %d POSTs same phone ===", n)
    payloads = [
        _payload(
            phone="212611288877",
            crid=f"rate-{index}-{uuid.uuid4().hex[:8]}",
            name="RateTest",
        )
        for index in range(n)
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(post, payloads))

    status_counts: dict[int, int] = {}
    for result in results:
        status_counts[result.status_code] = status_counts.get(result.status_code, 0) + 1
    LOG.info("status distribution: %s", status_counts)
    assert 200 in status_counts and 429 in status_counts, status_counts
    for result in results:
        if result.status_code == 429:
            assert result.headers.get("retry-after") or result.headers.get("Retry-After")
    return status_counts


def test_distinct_refs_under_load(load_db):
    refs = run_distinct_refs(_testclient_post, n=50)
    counters = sorted(int(ref.split("-")[-1]) for ref in refs)
    assert counters == list(range(1, 51))
    assert _booking_count(load_db) == 50
    assert _ref_counter_value(load_db) == 50


def test_idempotency_under_concurrent_replays(load_db):
    refs = run_idempotency_under_contention(
        _testclient_post,
        seed_first=True,
        attempts=10,
    )
    assert len(set(refs)) == 1
    assert _booking_count(load_db) == 1


def test_rate_limit_burst_under_load(load_db, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_bookings_per_phone", "5/hour")
    limiter.reset()
    status_counts = run_rate_limit_burst(_testclient_post, n=50)
    assert status_counts[200] == 5
    assert status_counts[429] == 45
    assert _booking_count(load_db) == 5


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--scenario",
        choices=["distinct", "idempotent", "rate_limit", "all"],
        default="all",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    post = lambda payload: _httpx_post(args.base_url, payload)
    scenarios = (
        [args.scenario]
        if args.scenario != "all"
        else ["distinct", "idempotent", "rate_limit"]
    )
    try:
        for scenario in scenarios:
            if scenario == "distinct":
                run_distinct_refs(post, n=50)
            elif scenario == "idempotent":
                run_idempotency_under_contention(post, seed_first=False, attempts=10)
            elif scenario == "rate_limit":
                run_rate_limit_burst(post, n=50)
    except AssertionError as exc:
        LOG.error("scenario FAILED: %s", exc)
        return 1
    LOG.info("=== ALL LOAD SCENARIOS PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
