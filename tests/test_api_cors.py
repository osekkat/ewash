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
