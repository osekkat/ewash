"""Tests for app.rate_limit slowapi integration."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest import TestCase

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from limits import parse
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request as StarletteRequest

from app import api as pwa_api, catalog, notifications, persistence
from app.config import settings
from app.db import init_db, make_engine
from app.main import app as main_app
from app.rate_limit import (
    PerPhoneRateLimitExceeded,
    _token_key_func,
    hit_phone_limit,
    limiter,
    per_phone_rate_limit_handler,
    rate_limit_exceeded_handler,
)
from app.security import hash_token


case = TestCase()


def _limited_client() -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    @app.get("/limited")
    @limiter.limit("1/minute")
    async def limited(request: Request, response: Response):
        return {"ok": True}

    return TestClient(app)


def _api_client() -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_exception_handler(PerPhoneRateLimitExceeded, per_phone_rate_limit_handler)
    app.include_router(pwa_api.router)
    pwa_api.install_exception_handlers(app)
    return TestClient(app)


def _request_with_headers(headers: dict[str, str]) -> StarletteRequest:
    return StarletteRequest(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/bookings",
            "headers": [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in headers.items()],
            "client": ("198.51.100.9", 12345),
        }
    )


@contextmanager
def _temporary_route_limit(endpoint_name: str, limit_str: str, *, index: int = 0):
    """Temporarily swap a route's slowapi limit. Token-keyed routes that
    stack a per-IP umbrella have two entries — pass ``index=1`` to swap
    the umbrella, leaving the per-token bucket alone (or vice versa)."""
    route_key = f"app.api.{endpoint_name}"
    route_limits = limiter._route_limits[route_key]
    original = route_limits[index].limit
    route_limits[index].limit = parse(limit_str)
    limiter.reset()
    try:
        yield
    finally:
        route_limits[index].limit = original
        limiter.reset()


def _ip_umbrella_index(endpoint_name: str) -> int:
    """Locate which ``_route_limits`` entry on a token-keyed endpoint is the
    per-IP umbrella (key_func == get_remote_address), not the per-token
    bucket. slowapi's storage order is decorator-registration order; the
    umbrella sits at a different index per route depending on which
    decorator was written innermost."""
    route_key = f"app.api.{endpoint_name}"
    route_limits = limiter._route_limits[route_key]
    for index, limit in enumerate(route_limits):
        if limit.key_func is get_remote_address:
            return index
    raise AssertionError(f"{route_key} has no per-IP umbrella decorator")


@pytest.fixture
def api_db(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'api-rate-limit.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    persistence._configured_engine.cache_clear()
    catalog.catalog_cache_clear()
    notifications.notification_cache_clear()

    async def noop_staff_alert(*_args, **_kwargs):
        return None

    monkeypatch.setattr(notifications, "notify_booking_confirmation_safe", noop_staff_alert)
    try:
        yield engine
    finally:
        persistence._configured_engine.cache_clear()
        catalog.catalog_cache_clear()
        notifications.notification_cache_clear()


def _booking_payload(*, phone: str = "212611204502", client_request_id: str | None = None) -> dict:
    return {
        "phone": phone,
        "name": "Rate Limit User",
        "category": "A",
        "vehicle": {"make": "Dacia Logan", "color": "Blanc"},
        "location": {"kind": "home", "pin_address": "Rate limit test"},
        "service_id": "svc_cpl",
        "date": "2026-12-04",
        "slot": "slot_11_13",
        "addon_ids": [],
        "client_request_id": client_request_id or str(uuid.uuid4()),
    }


def _assert_rate_limit_envelope(response):
    assert response.status_code == 429
    assert response.headers.get("Retry-After")
    assert response.headers.get("X-Ewash-Error-Code") == "rate_limit_exceeded"
    body = response.json()
    assert body["error_code"] == "rate_limit_exceeded"
    assert "Rate limit exceeded" in body["message"]


def test_limiter_import_and_main_app_state():
    case.assertIs(main_app.state.limiter, limiter)
    case.assertTrue(hasattr(limiter, "limit"))
    case.assertTrue(hasattr(limiter, "reset"))


def test_api_route_limits_match_documented_scope():
    # Each entry: route_key -> list of (limit_str, key_func) tuples, one per
    # ``@limiter.limit`` decorator on the handler. Token-keyed routes stack
    # a per-IP umbrella on top of their per-token bucket so an attacker
    # cycling garbage X-Ewash-Token values can't bypass the per-token cap
    # by spawning a fresh slowapi bucket per request (ewash-byd).
    expected = {
        "app.api.get_services": [
            (settings.rate_limit_catalog_per_ip, get_remote_address),
        ],
        "app.api.list_catalog_centers": [
            (settings.rate_limit_catalog_per_ip, get_remote_address),
        ],
        "app.api.list_catalog_time_slots": [
            (settings.rate_limit_catalog_per_ip, get_remote_address),
        ],
        "app.api.list_catalog_closed_dates": [
            (settings.rate_limit_catalog_per_ip, get_remote_address),
        ],
        "app.api.get_bootstrap": [
            (settings.rate_limit_catalog_per_ip, get_remote_address),
        ],
        "app.api.validate_promo": [
            (settings.rate_limit_promo_per_ip, get_remote_address),
        ],
        "app.api.create_booking": [
            (settings.rate_limit_bookings_per_ip, get_remote_address),
        ],
        "app.api.list_bookings": [
            (settings.rate_limit_bookings_list_per_token, _token_key_func),
            (settings.rate_limit_token_endpoints_per_ip, get_remote_address),
        ],
        "app.api.revoke_token": [
            (settings.rate_limit_token_revoke_per_token, _token_key_func),
            (settings.rate_limit_token_endpoints_per_ip, get_remote_address),
        ],
        "app.api.delete_my_account": [
            (settings.rate_limit_me_delete_per_token, _token_key_func),
            (settings.rate_limit_token_endpoints_per_ip, get_remote_address),
        ],
    }

    for route_key, decorators in expected.items():
        route_limits = limiter._route_limits.get(route_key)
        assert route_limits, f"{route_key} has no slowapi limit"
        assert len(route_limits) == len(decorators), (
            f"{route_key} has {len(route_limits)} limit decorators, "
            f"expected {len(decorators)}"
        )
        # slowapi stores decorators in reverse order (innermost decorator
        # runs first), so iterate the expected list in reverse too.
        for actual, (limit_str, key_func) in zip(route_limits, list(reversed(decorators))):
            assert actual.limit == parse(limit_str)
            assert actual.key_func is key_func


def test_catalog_categories_route_is_intentionally_unlimited():
    assert "app.api.list_catalog_categories" not in limiter._route_limits
    route = next(
        route
        for route in pwa_api.router.routes
        if route.path == "/api/v1/catalog/categories"
    )
    assert route.endpoint.__name__ == "list_catalog_categories"


def test_per_ip_decorator_blocks_second_request():
    client = _limited_client()

    first = client.get("/limited")
    second = client.get("/limited")

    case.assertEqual(first.status_code, 200)
    _assert_rate_limit_envelope(second)


def test_per_phone_cap_on_bookings(api_db, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_bookings_per_phone", "5/hour")
    client = _api_client()

    responses = [
        client.post(
            "/api/v1/bookings",
            json=_booking_payload(client_request_id=f"phone-cap-{index}"),
        )
        for index in range(6)
    ]

    assert [response.status_code for response in responses[:5]] == [200] * 5
    limited = responses[5]
    assert limited.status_code == 429
    assert limited.headers.get("Retry-After")
    # Per-phone caps used to surface as ``{"detail": {...}}`` (FastAPI's
    # default HTTPException envelope) while IP-caps from slowapi used a
    # flat ``{"error_code": "...", "message": "..."}`` body. The PWA reads
    # ``errBody.error_code`` directly so the per-phone case rendered as
    # ``http_429`` instead of the canonical ``rate_limit_exceeded``. The
    # unified handler in app.rate_limit.per_phone_rate_limit_handler
    # collapses both flows onto the same shape.
    assert limited.headers.get("X-Ewash-Error-Code") == "rate_limit_exceeded"
    body = limited.json()
    assert body["error_code"] == "rate_limit_exceeded"
    assert body["scope"] == "per_phone"
    assert "Too many bookings from this phone" in body["message"]


def test_per_ip_cap_on_bookings(api_db, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_bookings_per_phone", "1000/hour")
    client = _api_client()

    with _temporary_route_limit("create_booking", "20/hour"):
        responses = [
            client.post(
                "/api/v1/bookings",
                json=_booking_payload(
                    phone=f"21261120{index:04d}",
                    client_request_id=f"ip-cap-{index}",
                ),
            )
            for index in range(21)
        ]

    assert [response.status_code for response in responses[:20]] == [200] * 20
    _assert_rate_limit_envelope(responses[20])


def test_token_endpoints_per_ip_umbrella_blocks_garbage_token_spam(api_db):
    """Regression for ewash-byd. ``_token_key_func`` keys each *distinct*
    token string into its own slowapi bucket — without an IP umbrella an
    attacker rotating garbage ``X-Ewash-Token`` values would never trip the
    per-token cap on GET /bookings (or POST /tokens/revoke or DELETE /me)
    because each fake token spawns a fresh bucket. The dual-decorator stack
    adds a per-IP umbrella that caps the aggregate request rate from one
    origin regardless of how many distinct tokens are presented."""
    client = _api_client()

    # Use a tight 5/hour umbrella so the test doesn't need 600+ requests.
    # The per-token bucket is left alone — each garbage token would
    # otherwise sit in its own ample bucket and never trip the per-token
    # cap on its own.
    ip_index = _ip_umbrella_index("list_bookings")
    with _temporary_route_limit("list_bookings", "5/hour", index=ip_index):
        responses = [
            client.get(
                "/api/v1/bookings",
                headers={"X-Ewash-Token": f"garbage-{index:06d}"},
            )
            for index in range(7)
        ]

    # First 5 land on the underlying handler (each 401s with invalid_token
    # because the token doesn't resolve), then the IP umbrella fires.
    statuses = [r.status_code for r in responses]
    assert statuses[:5] == [401] * 5, f"unexpected statuses: {statuses}"
    assert statuses[5] == 429, f"6th request should be IP-capped: {statuses}"
    assert statuses[6] == 429, f"7th request should also be IP-capped: {statuses}"

    # The 429 carries the canonical envelope.
    _assert_rate_limit_envelope(responses[5])


def test_token_endpoints_per_ip_umbrella_also_caps_revoke_and_me_delete(api_db):
    """Same protection applies to the other two token-keyed routes."""
    client = _api_client()

    revoke_ip_index = _ip_umbrella_index("revoke_token")
    with _temporary_route_limit("revoke_token", "3/hour", index=revoke_ip_index):
        responses = [
            client.post(
                "/api/v1/tokens/revoke",
                json={"scope": "current"},
                headers={"X-Ewash-Token": f"revoke-garbage-{index:06d}"},
            )
            for index in range(5)
        ]
    statuses = [r.status_code for r in responses]
    assert statuses[:3] == [401] * 3, statuses
    assert statuses[3] == 429, statuses
    assert statuses[4] == 429, statuses

    me_ip_index = _ip_umbrella_index("delete_my_account")
    with _temporary_route_limit("delete_my_account", "3/hour", index=me_ip_index):
        responses = [
            client.request(
                "DELETE",
                "/api/v1/me",
                json={"confirm": "I confirm I want to delete my data"},
                headers={"X-Ewash-Token": f"me-garbage-{index:06d}"},
            )
            for index in range(5)
        ]
    statuses = [r.status_code for r in responses]
    assert statuses[:3] == [401] * 3, statuses
    assert statuses[3] == 429, statuses
    assert statuses[4] == 429, statuses


def test_per_ip_cap_on_promo_validate():
    client = _api_client()

    with _temporary_route_limit("validate_promo", "60/hour"):
        responses = [
            client.post(
                "/api/v1/promos/validate",
                json={"code": "YS26", "category": "A"},
            )
            for _ in range(61)
        ]

    assert [response.status_code for response in responses[:60]] == [200] * 60
    _assert_rate_limit_envelope(responses[60])


def test_per_token_cap_on_bookings_list(api_db, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_bookings_per_phone", "1000/hour")
    client = _api_client()
    created = client.post(
        "/api/v1/bookings",
        json=_booking_payload(client_request_id="list-token-cap"),
    )
    assert created.status_code == 200
    token = created.json()["bookings_token"]

    with _temporary_route_limit("list_bookings", "60/hour"):
        responses = [
            client.get("/api/v1/bookings", headers={"X-Ewash-Token": token})
            for _ in range(61)
        ]

    assert [response.status_code for response in responses[:60]] == [200] * 60
    _assert_rate_limit_envelope(responses[60])


def test_caps_independent(api_db, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_bookings_per_phone", "1000/hour")
    client = _api_client()

    with (
        _temporary_route_limit("create_booking", "2/hour"),
        _temporary_route_limit("validate_promo", "2/hour"),
    ):
        booking_1 = client.post(
            "/api/v1/bookings",
            json=_booking_payload(phone="212611300001", client_request_id="independent-1"),
        )
        booking_2 = client.post(
            "/api/v1/bookings",
            json=_booking_payload(phone="212611300002", client_request_id="independent-2"),
        )
        booking_limited = client.post(
            "/api/v1/bookings",
            json=_booking_payload(phone="212611300003", client_request_id="independent-3"),
        )
        promo_1 = client.post(
            "/api/v1/promos/validate",
            json={"code": "YS26", "category": "A"},
        )
        promo_2 = client.post(
            "/api/v1/promos/validate",
            json={"code": "YS26", "category": "A"},
        )
        promo_limited = client.post(
            "/api/v1/promos/validate",
            json={"code": "YS26", "category": "A"},
        )

    assert [booking_1.status_code, booking_2.status_code] == [200, 200]
    _assert_rate_limit_envelope(booking_limited)
    assert [promo_1.status_code, promo_2.status_code] == [200, 200]
    _assert_rate_limit_envelope(promo_limited)


def test_hit_phone_limit_raises_with_retry_after_and_error_body():
    hit_phone_limit("212611204502", "1/minute")

    with pytest.raises(PerPhoneRateLimitExceeded) as exc_info:
        hit_phone_limit("212611204502", "1/minute")

    exc = exc_info.value
    case.assertEqual(exc.status_code, 429)
    case.assertEqual(exc.detail["error_code"], "rate_limit_exceeded")
    case.assertEqual(exc.detail["scope"], "per_phone")
    case.assertIn("Retry-After", exc.headers)
    case.assertGreaterEqual(int(exc.headers["Retry-After"]), 1)


def test_phone_limit_keys_are_per_phone():
    hit_phone_limit("212611204502", "1/minute")

    hit_phone_limit("212611204503", "1/minute")


def test_token_key_func_hashes_token_header():
    sample_value = "opaque-value-for-test"
    request = _request_with_headers({"X-Ewash-Token": sample_value})

    key = _token_key_func(request)

    case.assertEqual(key, f"token:{hash_token(sample_value)[:16]}")
    case.assertNotIn(sample_value, key)


def test_token_key_func_falls_back_to_remote_address():
    request = _request_with_headers({})

    case.assertEqual(_token_key_func(request), "198.51.100.9")
