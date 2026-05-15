"""E2E-style bootstrap ETag cache round-trip for PWA callers.

This test keeps the server in-process but exercises the same HTTP contract the
zero-build PWA needs: first call receives a JSON body plus ETag, second
identical call sends ``If-None-Match`` and receives ``304``, and the caller
resolves the cached JSON body instead of ``None``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import api
from app.rate_limit import limiter


def _client() -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api.router)
    api.install_exception_handlers(app)
    return TestClient(app)


@dataclass
class BootstrapResult:
    status_code: int
    body: dict[str, Any]
    etag: str


class CachedBootstrapCaller:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self._cache: dict[str, BootstrapResult] = {}

    def get_bootstrap(self, *, category: str = "", promo: str = "") -> BootstrapResult:
        cache_key = f"category={category.upper()}&promo={promo.upper()}"
        cached = self._cache.get(cache_key)
        headers = {"If-None-Match": cached.etag} if cached else {}
        params = {key: value for key, value in {"category": category, "promo": promo}.items() if value}

        response = self.client.get("/api/v1/bootstrap", params=params, headers=headers)
        etag = response.headers.get("ETag", "")

        if response.status_code == 304:
            assert cached is not None
            return BootstrapResult(status_code=304, body=cached.body, etag=etag)

        assert response.status_code == 200
        assert etag
        result = BootstrapResult(status_code=200, body=response.json(), etag=etag)
        self._cache[cache_key] = result
        return result


def test_pwa_bootstrap_etag_replay_returns_cached_body_to_caller() -> None:
    with _client() as client:
        caller = CachedBootstrapCaller(client)
        first = caller.get_bootstrap(category="B", promo="ys26")
        second = caller.get_bootstrap(category="B", promo="YS26")

    assert first.status_code == 200
    assert second.status_code == 304
    assert second.etag == first.etag
    assert second.body == first.body
    assert second.body["services"]["wash"]
