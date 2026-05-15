"""Tests for /api/v1/catalog/* endpoints (read-only catalog projection)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import install_exception_handlers, router


def _make_client() -> TestClient:
    """Mount the /api/v1 router on a fresh FastAPI app, like the prod wiring."""
    app = FastAPI()
    app.include_router(router)
    install_exception_handlers(app)
    return TestClient(app)


def test_categories_endpoint_returns_four_rows():
    client = _make_client()
    response = client.get("/api/v1/catalog/categories")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 4


def test_categories_endpoint_returns_three_cars_and_one_moto():
    client = _make_client()
    payload = client.get("/api/v1/catalog/categories").json()
    kinds = [row["kind"] for row in payload]
    assert kinds.count("car") == 3
    assert kinds.count("moto") == 1


def test_categories_endpoint_uses_pricing_category_keys_as_ids():
    # Critical: the `id` field must match the BookingCreateRequest.category
    # contract (A / B / C / MOTO), NOT the catalog row id (veh_a / veh_b / …).
    # If this regresses, every PWA booking request would 422 on the category
    # field because the PWA reads `id` and submits it as `category`.
    client = _make_client()
    payload = client.get("/api/v1/catalog/categories").json()
    ids = {row["id"] for row in payload}
    assert ids == {"A", "B", "C", "MOTO"}


def test_categories_endpoint_returns_clean_api_labels_not_bot_titles():
    # The bot's list-row titles embed "A — " / "B — " / "🏍️ " prefixes
    # which the PWA neither wants nor needs.
    client = _make_client()
    payload = client.get("/api/v1/catalog/categories").json()
    labels = {row["id"]: row["label"] for row in payload}
    assert labels["A"] == "Citadine"
    assert labels["B"] == "Berline / SUV"
    assert labels["C"] == "Grande berline/SUV"
    assert labels["MOTO"] == "Moto/Scooter"


def test_categories_endpoint_includes_sub_examples_from_catalog():
    # `sub` carries the example-vehicles string from VEHICLE_CATEGORIES so the
    # PWA can render "Clio, Sandero, …" under each pill without a second call.
    client = _make_client()
    payload = client.get("/api/v1/catalog/categories").json()
    subs = {row["id"]: row["sub"] for row in payload}
    assert "Clio" in subs["A"]
    assert "Megane" in subs["B"]
    assert "X5" in subs["C"]
    assert "Deux roues" in subs["MOTO"]


def test_categories_endpoint_payload_shape_matches_pydantic_model():
    # Every row has exactly the 4 fields declared in CategoryOut and nothing
    # extra (Pydantic's response_model would silently strip extras; this
    # double-checks we're not relying on that behavior).
    client = _make_client()
    payload = client.get("/api/v1/catalog/categories").json()
    for row in payload:
        assert set(row.keys()) == {"id", "label", "sub", "kind"}
        assert isinstance(row["id"], str)
        assert isinstance(row["label"], str)
        assert isinstance(row["sub"], str)
        assert row["kind"] in {"car", "moto"}


def test_categories_endpoint_kind_aligns_with_moto_price_category():
    # The moto row's kind must reflect MOTO_PRICE_CATEGORY so downstream code
    # can switch on `kind == "moto"` instead of string-matching the id.
    client = _make_client()
    payload = client.get("/api/v1/catalog/categories").json()
    moto_row = next(row for row in payload if row["id"] == "MOTO")
    car_rows = [row for row in payload if row["id"] != "MOTO"]
    assert moto_row["kind"] == "moto"
    assert all(row["kind"] == "car" for row in car_rows)
