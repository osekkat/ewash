"""Tests for PWA catalog endpoints in app.api."""
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


def test_services_car_category_returns_wash_and_detailing_groups() -> None:
    with _client() as client:
        response = client.get("/api/v1/catalog/services?category=B")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"wash", "detailing"}
    assert len(body["wash"]) == len(catalog.SERVICES_WASH)
    assert len(body["detailing"]) == len(catalog.SERVICES_DETAILING)
    assert body["wash"][0] == {
        "id": "svc_ext",
        "name": "L'Extérieur",
        "desc": "Carrosserie, vitres, jantes + wax 1 semaine",
        "price_dh": catalog.service_price("svc_ext", "B"),
        "regular_price_dh": None,
        "bucket": "wash",
    }


def test_services_moto_category_returns_moto_group_only() -> None:
    with _client() as client:
        response = client.get("/api/v1/catalog/services?category=MOTO")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"moto"}
    assert len(body["moto"]) == len(catalog.SERVICES_MOTO)
    assert all(item["bucket"] == "moto" for item in body["moto"])
    assert all(item["regular_price_dh"] is None for item in body["moto"])


def test_services_valid_promo_populates_strike_through_price() -> None:
    with _client() as client:
        response = client.get("/api/v1/catalog/services?category=B&promo=ys26")

    assert response.status_code == 200
    body = response.json()
    complete = next(item for item in body["wash"] if item["id"] == "svc_cpl")
    assert complete["price_dh"] == catalog.service_price(
        "svc_cpl",
        "B",
        promo_code="YS26",
    )
    assert complete["regular_price_dh"] == catalog.service_price("svc_cpl", "B")
    assert complete["price_dh"] < complete["regular_price_dh"]


def test_services_invalid_promo_matches_no_promo_response() -> None:
    with _client() as client:
        no_promo = client.get("/api/v1/catalog/services?category=C")
        invalid_promo = client.get("/api/v1/catalog/services?category=C&promo=HPL25")

    assert no_promo.status_code == 200
    assert invalid_promo.status_code == 200
    assert invalid_promo.json() == no_promo.json()
    for group in invalid_promo.json().values():
        assert all(item["regular_price_dh"] is None for item in group)


def test_services_logs_counts_for_car_and_moto(caplog) -> None:
    caplog.set_level(logging.INFO, logger="ewash.api")

    with _client() as client:
        client.get("/api/v1/catalog/services?category=A")
        client.get("/api/v1/catalog/services?category=MOTO")

    assert any(
        "catalog.services listed category=A promo=- count_wash=3 count_detailing=7"
        in rec.message
        for rec in caplog.records
    )
    assert any(
        "catalog.services listed category=MOTO promo=- count_moto=2" in rec.message
        for rec in caplog.records
    )


# ── /catalog/categories ───────────────────────────────────────────────────


def test_categories_endpoint_returns_four_rows():
    with _client() as client:
        response = client.get("/api/v1/catalog/categories")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 4


def test_categories_endpoint_returns_three_cars_and_one_moto():
    with _client() as client:
        payload = client.get("/api/v1/catalog/categories").json()
    kinds = [row["kind"] for row in payload]
    assert kinds.count("car") == 3
    assert kinds.count("moto") == 1


def test_categories_endpoint_uses_pricing_category_keys_as_ids():
    # Critical: the `id` field must match the BookingCreateRequest.category
    # contract (A / B / C / MOTO), NOT the catalog row id (veh_a / veh_b / …).
    # If this regresses, every PWA booking request would 422 on the category
    # field because the PWA reads `id` and submits it as `category`.
    with _client() as client:
        payload = client.get("/api/v1/catalog/categories").json()
    ids = {row["id"] for row in payload}
    assert ids == {"A", "B", "C", "MOTO"}


def test_categories_endpoint_returns_clean_api_labels_not_bot_titles():
    # The bot's list-row titles embed "A — " / "B — " / "🏍️ " prefixes
    # which the PWA neither wants nor needs.
    with _client() as client:
        payload = client.get("/api/v1/catalog/categories").json()
    labels = {row["id"]: row["label"] for row in payload}
    assert labels["A"] == "Citadine"
    assert labels["B"] == "Berline / SUV"
    assert labels["C"] == "Grande berline/SUV"
    assert labels["MOTO"] == "Moto/Scooter"


def test_categories_endpoint_includes_sub_examples_from_catalog():
    # `sub` carries the example-vehicles string from VEHICLE_CATEGORIES so the
    # PWA can render "Clio, Sandero, …" under each pill without a second call.
    with _client() as client:
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
    with _client() as client:
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
    with _client() as client:
        payload = client.get("/api/v1/catalog/categories").json()
    moto_row = next(row for row in payload if row["id"] == "MOTO")
    car_rows = [row for row in payload if row["id"] != "MOTO"]
    assert moto_row["kind"] == "moto"
    assert all(row["kind"] == "car" for row in car_rows)
