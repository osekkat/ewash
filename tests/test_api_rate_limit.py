"""Tests for app.rate_limit slowapi integration."""
from __future__ import annotations

from unittest import TestCase

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request as StarletteRequest

from app.main import app as main_app
from app.rate_limit import (
    PerPhoneRateLimitExceeded,
    _token_key_func,
    hit_phone_limit,
    limiter,
)
from app.security import hash_token


case = TestCase()


def _limited_client() -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/limited")
    @limiter.limit("1/minute")
    async def limited(request: Request, response: Response):
        return {"ok": True}

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


def test_limiter_import_and_main_app_state():
    case.assertIs(main_app.state.limiter, limiter)
    case.assertTrue(hasattr(limiter, "limit"))
    case.assertTrue(hasattr(limiter, "reset"))


def test_per_ip_decorator_blocks_second_request():
    client = _limited_client()

    first = client.get("/limited")
    second = client.get("/limited")

    case.assertEqual(first.status_code, 200)
    case.assertEqual(second.status_code, 429)


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
