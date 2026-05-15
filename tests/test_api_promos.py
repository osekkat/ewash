"""Tests for POST /api/v1/promos/validate."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import api, catalog


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(api.router)
    api.install_exception_handlers(app)
    return TestClient(app)


def test_promo_validate_known_code_for_car_category_returns_discounts():
    with _client() as client:
        response = client.post(
            "/api/v1/promos/validate",
            json={"code": "YS26", "category": "B"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["label"]  # non-empty partner label
    # Should include svc_cpl at 110 (YS26 promo on B category).
    assert body["discounted_prices"]["svc_cpl"] == catalog.service_price(
        "svc_cpl", "B", promo_code="YS26"
    )


def test_promo_validate_normalizes_lowercase_and_whitespace():
    with _client() as client:
        response = client.post(
            "/api/v1/promos/validate",
            json={"code": "  ys26 ", "category": "B"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True


def test_promo_validate_moto_returns_valid_but_no_discounts():
    """YS26 has no moto entries in the partner grid — moto is intentionally
    excluded. The response is still valid=True with an empty discount map."""
    with _client() as client:
        response = client.post(
            "/api/v1/promos/validate",
            json={"code": "YS26", "category": "MOTO"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["discounted_prices"] == {}


def test_promo_validate_unknown_code_returns_200_with_valid_false():
    """Unknown codes must NOT 404 — that would let an attacker enumerate
    valid codes by probing for the absence of a 404."""
    with _client() as client:
        response = client.post(
            "/api/v1/promos/validate",
            json={"code": "NOPE", "category": "B"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["discounted_prices"] == {}


def test_promo_validate_garbage_code_returns_200_with_valid_false():
    # Pydantic's max_length=40 catches strings >40 chars; this one is well
    # under and tests the normalize_promo_code rejection path (looks like a
    # code but doesn't match the partner grid).
    with _client() as client:
        response = client.post(
            "/api/v1/promos/validate",
            json={"code": "X" * 39, "category": "C"},
        )
    assert response.status_code == 200
    assert response.json()["valid"] is False


def test_promo_validate_rejects_blank_code_via_pydantic():
    """The schema enforces min_length=1 so the handler never sees an empty
    code. Returns 422, not 200/false."""
    with _client() as client:
        response = client.post(
            "/api/v1/promos/validate",
            json={"code": "", "category": "B"},
        )
    assert response.status_code == 422


def test_promo_validate_rejects_unknown_category():
    """Pydantic Literal["A","B","C","MOTO"] should 422 a malformed category."""
    with _client() as client:
        response = client.post(
            "/api/v1/promos/validate",
            json={"code": "YS26", "category": "Z"},
        )
    assert response.status_code == 422


def test_promo_validate_lowercase_category_is_accepted():
    """The schema's field_validator uppercases the category — submitting 'b'
    must round-trip the same as 'B'."""
    with _client() as client:
        lower = client.post(
            "/api/v1/promos/validate",
            json={"code": "YS26", "category": "b"},
        )
        upper = client.post(
            "/api/v1/promos/validate",
            json={"code": "YS26", "category": "B"},
        )
    assert lower.status_code == 200
    assert upper.status_code == 200
    assert lower.json() == upper.json()


def test_promo_validate_discount_map_omits_services_with_no_saving():
    """A discount equal to the public price doesn't count as a saving — the
    PWA should not render a strike-through. The endpoint omits those rows."""
    with _client() as client:
        body = client.post(
            "/api/v1/promos/validate",
            json={"code": "YS26", "category": "B"},
        ).json()
    for service_id, discounted in body["discounted_prices"].items():
        public = catalog.public_service_price(service_id, "B")
        assert discounted < public, (
            f"discounted_prices contains {service_id}={discounted} "
            f"but public price is also {public}"
        )


def test_promo_validate_logs_outcome(caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")
    with _client() as client:
        client.post(
            "/api/v1/promos/validate",
            json={"code": "YS26", "category": "B"},
        )
        client.post(
            "/api/v1/promos/validate",
            json={"code": "NOPE", "category": "B"},
        )
    messages = [rec.message for rec in caplog.records]
    # Happy path logs the normalized code; the rejection path logs "code=-"
    # because normalize_promo_code() returns None for non-grid codes, and the
    # handler short-circuits before re-deriving the input string.
    assert any(
        "promos.validate code=YS26 category=B valid=True" in line for line in messages
    )
    assert any(
        "promos.validate code=- category=B valid=False" in line for line in messages
    )


def test_promo_validate_rejects_unknown_field_via_strict_base():
    """StrictBase declares extra='forbid'. Sending stray fields is 422."""
    with _client() as client:
        response = client.post(
            "/api/v1/promos/validate",
            json={"code": "YS26", "category": "B", "addons": ["svc_pol"]},
        )
    assert response.status_code == 422
