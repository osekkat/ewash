"""Structured access-log contract for the PWA API surface."""
from __future__ import annotations

import hashlib
import logging
import re
from unittest import TestCase

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app import main

case = TestCase()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _client() -> TestClient:
    app = FastAPI()
    main._configure_access_logging(app)

    @app.get("/api/v1/ok")
    async def ok(request: Request):
        request.state.phone_normalized = "+212611204502"
        request.state.booking_ref = "EW-2026-0001"
        return {"ok": True}

    @app.get("/api/v1/error")
    async def error(request: Request):
        request.state.phone_normalized = "212611204502"
        response = JSONResponse({"error_code": "invalid_token"}, status_code=401)
        response.headers["X-Ewash-Error-Code"] = "invalid_token"
        return response

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return TestClient(app)


def _api_records(caplog):
    return [
        record
        for record in caplog.records
        if record.name == "ewash.api" and record.getMessage().startswith("ewash.api ")
    ]


def test_api_request_emits_exactly_one_structured_log(caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")
    client = _client()

    response = client.get("/api/v1/ok")

    case.assertEqual(response.status_code, 200)
    records = _api_records(caplog)
    case.assertEqual(len(records), 1)
    message = records[0].getMessage()
    case.assertIn("endpoint=/api/v1/ok", message)
    case.assertIn("method=GET", message)
    case.assertIn("status=200", message)
    case.assertRegex(message, r"duration_ms=\d+\.\d")


def test_phone_and_ip_are_logged_as_hex_prefixes(caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")
    client = _client()

    client.get("/api/v1/ok")

    message = _api_records(caplog)[0].getMessage()
    case.assertNotIn("+212611204502", message)
    case.assertNotIn("testclient", message)
    case.assertIn(f"phone_hash={_digest('+212611204502')}", message)
    case.assertIn(f"source_ip_hash={_digest('testclient')}", message)
    case.assertRegex(message, r"phone_hash=[0-9a-f]{12}")
    case.assertRegex(message, r"source_ip_hash=[0-9a-f]{12}")


def test_booking_ref_is_logged_when_handler_sets_it(caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")
    client = _client()

    client.get("/api/v1/ok")

    message = _api_records(caplog)[0].getMessage()
    case.assertIn("ref=EW-2026-0001", message)


def test_error_code_header_is_logged(caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")
    client = _client()

    response = client.get("/api/v1/error")

    case.assertEqual(response.status_code, 401)
    records = _api_records(caplog)
    case.assertEqual(len(records), 1)
    message = records[0].getMessage()
    case.assertIn("status=401", message)
    case.assertIn("error_code=invalid_token", message)


def test_non_api_request_does_not_emit_api_access_log(caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")
    client = _client()

    response = client.get("/health")

    case.assertEqual(response.status_code, 200)
    case.assertEqual(_api_records(caplog), [])


def test_hash_helper_returns_dash_for_missing_values():
    case.assertEqual(main._hash_log_value(""), "-")
    hashed = main._hash_log_value("abc")
    case.assertEqual(hashed, _digest("abc"))
    case.assertIsNotNone(re.fullmatch(r"[0-9a-f]{12}", hashed))
