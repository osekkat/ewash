"""Tests for the PWA API CORS middleware wiring."""
from __future__ import annotations

import logging
from unittest import TestCase

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main

case = TestCase()


def _client_with_cors(
    monkeypatch,
    *,
    allowed_origins: str = "",
    allowed_origin_regex: str = "",
    api_enabled: bool = True,
) -> TestClient:
    monkeypatch.setattr(main.settings, "allowed_origins", allowed_origins)
    monkeypatch.setattr(main.settings, "allowed_origin_regex", allowed_origin_regex)
    monkeypatch.setattr(main.settings, "api_enabled", api_enabled)

    app = FastAPI()

    @app.get("/api/v1/bootstrap")
    async def bootstrap():
        return {"ok": True}

    main._configure_cors(app)
    return TestClient(app)


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/api/v1/bootstrap",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Ewash-Token, If-None-Match",
        },
    )


def test_options_bootstrap_allows_exact_origin(monkeypatch):
    origin = "https://ewash-pwa.vercel.app"
    client = _client_with_cors(monkeypatch, allowed_origins=origin)

    response = _preflight(client, origin)

    case.assertEqual(response.status_code, 200)
    case.assertEqual(response.headers["access-control-allow-origin"], origin)
    case.assertIn("GET", response.headers["access-control-allow-methods"])
    case.assertIn("X-Ewash-Token", response.headers["access-control-allow-headers"])


def test_options_bootstrap_allows_regex_origin(monkeypatch):
    origin = "https://ewash-mobile-app-git-feature-x.vercel.app"
    regex = r"^https://ewash-mobile-app-.*\.vercel\.app$"
    client = _client_with_cors(monkeypatch, allowed_origin_regex=regex)

    response = _preflight(client, origin)

    case.assertEqual(response.status_code, 200)
    case.assertEqual(response.headers["access-control-allow-origin"], origin)


def test_options_bootstrap_rejects_disallowed_origin(monkeypatch):
    client = _client_with_cors(
        monkeypatch,
        allowed_origins="https://ewash-pwa.vercel.app",
        allowed_origin_regex=r"^https://ewash-mobile-app-.*\.vercel\.app$",
    )

    response = _preflight(client, "https://evil.com")

    case.assertNotIn("access-control-allow-origin", response.headers)


def test_empty_cors_configuration_logs_warning(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="ewash")

    _client_with_cors(monkeypatch)

    case.assertTrue(
        any(
            "API is enabled but CORS is not configured" in record.getMessage()
            for record in caplog.records
        )
    )


def test_options_bootstrap_advertises_get_post_options_methods(monkeypatch):
    # The PWA only ever sends GET + POST, but the spec ships all three so a
    # future addition (e.g. DELETE /api/v1/me for data erasure) doesn't have
    # to be re-allowed here. OPTIONS is required for preflight itself.
    origin = "https://ewash-pwa.vercel.app"
    client = _client_with_cors(monkeypatch, allowed_origins=origin)

    response = _preflight(client, origin)

    case.assertEqual(response.status_code, 200)
    advertised = {
        method.strip().upper()
        for method in response.headers["access-control-allow-methods"].split(",")
    }
    case.assertTrue({"GET", "POST", "OPTIONS"}.issubset(advertised))


def test_options_bootstrap_advertises_pwa_request_headers(monkeypatch):
    # The PWA sends Content-Type for JSON bodies, X-Ewash-Token for the
    # token-scoped read paths, and If-None-Match for the bootstrap ETag.
    # All three must be on the allow-list or the browser blocks the request.
    origin = "https://ewash-pwa.vercel.app"
    client = _client_with_cors(monkeypatch, allowed_origins=origin)

    response = _preflight(client, origin)

    case.assertEqual(response.status_code, 200)
    advertised = {
        header.strip().lower()
        for header in response.headers["access-control-allow-headers"].split(",")
    }
    case.assertTrue({"content-type", "x-ewash-token", "if-none-match"}.issubset(advertised))


def test_options_bootstrap_does_not_advertise_credentials(monkeypatch):
    # Auth uses the X-Ewash-Token request header, never cookies. Sending
    # ``Access-Control-Allow-Credentials: true`` would force us to ban
    # wildcard origins and complicate the regex; it must not appear.
    origin = "https://ewash-pwa.vercel.app"
    client = _client_with_cors(monkeypatch, allowed_origins=origin)

    response = _preflight(client, origin)

    lowered_headers = {name.lower() for name in response.headers}
    case.assertNotIn("access-control-allow-credentials", lowered_headers)


def test_api_disabled_skips_cors_middleware(monkeypatch):
    # When EWASH_API_ENABLED is false the wiring short-circuits and no CORS
    # middleware is added. A bare GET-only FastAPI app returns 405 for OPTIONS
    # and emits no Access-Control headers — confirming the feature flag fully
    # disables the surface.
    client = _client_with_cors(
        monkeypatch,
        allowed_origins="https://ewash-pwa.vercel.app",
        api_enabled=False,
    )

    response = _preflight(client, "https://ewash-pwa.vercel.app")

    case.assertEqual(response.status_code, 405)
    lowered_headers = {name.lower() for name in response.headers}
    case.assertNotIn("access-control-allow-origin", lowered_headers)


def test_api_enabled_mounts_router(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="ewash")
    monkeypatch.setattr(main.settings, "api_enabled", True)
    app = FastAPI()

    main._configure_api(app)
    response = TestClient(app).get("/api/v1/catalog/categories")

    case.assertEqual(response.status_code, 200)
    case.assertTrue(
        any(
            "ewash.api enabled - /api/v1/* mounted" in record.getMessage()
            for record in caplog.records
        )
    )


def test_api_disabled_leaves_router_unmounted(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="ewash")
    monkeypatch.setattr(main.settings, "api_enabled", False)
    app = FastAPI()

    main._configure_api(app)
    response = TestClient(app).get("/api/v1/catalog/categories")

    case.assertEqual(response.status_code, 404)
    case.assertTrue(
        any(
            "ewash.api disabled - /api/v1/* NOT mounted" in record.getMessage()
            for record in caplog.records
        )
    )


def test_api_flag_does_not_affect_webhook_route(monkeypatch):
    for enabled in (True, False):
        monkeypatch.setattr(main.settings, "api_enabled", enabled)
        app = FastAPI()

        @app.get("/webhook")
        async def webhook():
            return {"ok": True}

        main._configure_api(app)
        response = TestClient(app).get("/webhook")

        case.assertEqual(response.status_code, 200)
        case.assertEqual(response.json(), {"ok": True})
