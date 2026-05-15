"""Feature-flag coverage for the PWA API router."""
from __future__ import annotations

import logging
from unittest import TestCase

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main

case = TestCase()


def _make_app(
    monkeypatch,
    *,
    api_enabled: bool,
    allowed_origins: str = "",
) -> TestClient:
    monkeypatch.setattr(main.settings, "api_enabled", api_enabled)
    monkeypatch.setattr(main.settings, "allowed_origins", allowed_origins)
    monkeypatch.setattr(main.settings, "allowed_origin_regex", "")

    app = FastAPI()
    app.state.limiter = main.limiter
    app.add_exception_handler(
        main.RateLimitExceeded,
        main._rate_limit_exceeded_handler,
    )
    main._configure_cors(app)
    main._configure_api(app)
    app.add_api_route("/health", main.health, methods=["GET"])
    app.add_api_route("/webhook", main.verify_webhook, methods=["GET"])
    app.include_router(main.admin.router)
    return TestClient(app)


def test_api_router_mounted_when_flag_true(monkeypatch):
    client = _make_app(monkeypatch, api_enabled=True)

    response = client.get("/api/v1/catalog/categories")

    case.assertEqual(response.status_code, 200)


def test_api_router_unmounted_when_flag_false(monkeypatch):
    client = _make_app(monkeypatch, api_enabled=False)

    response = client.get("/api/v1/catalog/categories")

    case.assertEqual(response.status_code, 404)


def test_webhook_path_works_regardless_of_flag(monkeypatch):
    for enabled in (True, False):
        client = _make_app(monkeypatch, api_enabled=enabled)
        invalid_token = f"{main.settings.meta_verify_token}-invalid"

        response = client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": invalid_token,
                "hub.challenge": "x",
            },
        )

        case.assertEqual(response.status_code, 403)


def test_admin_path_works_regardless_of_flag(monkeypatch):
    for enabled in (True, False):
        client = _make_app(monkeypatch, api_enabled=enabled)

        response = client.get("/admin")

        case.assertIn(response.status_code, {200, 401, 503})


def test_health_works_regardless_of_flag(monkeypatch):
    for enabled in (True, False):
        client = _make_app(monkeypatch, api_enabled=enabled)

        response = client.get("/health")

        case.assertEqual(response.status_code, 200)
        case.assertEqual(response.json(), {"status": "ok", "version": main.APP_VERSION})


def test_cors_middleware_skipped_when_flag_false(monkeypatch):
    client = _make_app(
        monkeypatch,
        api_enabled=False,
        allowed_origins="https://ewash-mobile-app.vercel.app",
    )

    response = client.options(
        "/api/v1/catalog/categories",
        headers={
            "Origin": "https://ewash-mobile-app.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )

    lowered_headers = {name.lower() for name in response.headers}
    case.assertEqual(response.status_code, 404)
    case.assertNotIn("access-control-allow-origin", lowered_headers)


def test_startup_log_reflects_flag_state(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="ewash")

    _make_app(monkeypatch, api_enabled=True)

    case.assertTrue(
        any(
            "ewash.api enabled - /api/v1/* mounted" in record.getMessage()
            for record in caplog.records
        )
    )

    caplog.clear()
    caplog.set_level(logging.WARNING, logger="ewash")

    _make_app(monkeypatch, api_enabled=False)

    case.assertTrue(
        any(
            "ewash.api disabled - /api/v1/* NOT mounted" in record.getMessage()
            for record in caplog.records
        )
    )
