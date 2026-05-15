"""Tests for PWA catalog endpoints in app.api."""
from __future__ import annotations

import logging
from unittest import TestCase

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import api, catalog
from app.rate_limit import limiter


def _client() -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api.router)
    api.install_exception_handlers(app)
    return TestClient(app)


# ── /bootstrap ────────────────────────────────────────────────────────────


def test_bootstrap_without_category_returns_shell_shape():
    with _client() as client:
        response = client.get("/api/v1/bootstrap")

    case = TestCase()
    assert response.status_code == 200
    assert response.headers["ETag"].startswith('W/"')
    assert response.headers["Cache-Control"] == "public, max-age=60, stale-while-revalidate=300"
    body = response.json()
    assert body["services"] == {}
    assert body["categories"]
    assert body["centers"]
    assert body["time_slots"]
    assert "closed_dates" in body
    case.assertEqual(body["staff_contact"], {"whatsapp_phone": "", "available": False})
    assert body["catalog_version"] == catalog.compute_catalog_etag_seed()


def test_bootstrap_with_category_populates_services_for_that_category():
    with _client() as client:
        response = client.get("/api/v1/bootstrap?category=A")

    assert response.status_code == 200
    body = response.json()
    assert set(body["services"]) == {"wash", "detailing"}
    assert len(body["services"]["wash"]) == len(catalog.SERVICES_WASH)
    assert body["services"]["wash"][0]["price_dh"] == catalog.service_price("svc_ext", "A")


def test_bootstrap_etag_304_round_trip_without_category():
    with _client() as client:
        first = client.get("/api/v1/bootstrap")
        second = client.get("/api/v1/bootstrap", headers={"If-None-Match": first.headers["ETag"]})

    assert first.status_code == 200
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["ETag"] == first.headers["ETag"]
    assert second.headers["Cache-Control"] == "public, max-age=60, stale-while-revalidate=300"


def test_bootstrap_etag_304_round_trip_with_category_and_promo():
    with _client() as client:
        first = client.get("/api/v1/bootstrap?category=B&promo=ys26")
        second = client.get(
            "/api/v1/bootstrap?category=B&promo=YS26",
            headers={"If-None-Match": first.headers["ETag"]},
        )

    assert first.status_code == 200
    assert second.status_code == 304
    assert second.headers["ETag"] == first.headers["ETag"]


def test_bootstrap_etag_differs_without_and_with_category():
    with _client() as client:
        no_category = client.get("/api/v1/bootstrap")
        category_a = client.get("/api/v1/bootstrap?category=A")

    assert no_category.headers["ETag"] != category_a.headers["ETag"]


def test_bootstrap_etag_differs_per_category():
    with _client() as client:
        category_a = client.get("/api/v1/bootstrap?category=A")
        category_b = client.get("/api/v1/bootstrap?category=B")

    assert category_a.headers["ETag"] != category_b.headers["ETag"]


def test_bootstrap_etag_differs_per_promo():
    with _client() as client:
        no_promo = client.get("/api/v1/bootstrap?category=B")
        promo = client.get("/api/v1/bootstrap?category=B&promo=YS26")

    assert no_promo.headers["ETag"] != promo.headers["ETag"]


def test_bootstrap_catalog_edit_invalidates_etag(monkeypatch, tmp_path):
    from app import catalog as catalog_module
    from app.config import settings
    from app.db import init_db, make_engine

    db_url = f"sqlite+pysqlite:///{tmp_path / 'api-bootstrap-catalog.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    catalog_module.catalog_cache_clear()
    try:
        with _client() as client:
            before = client.get("/api/v1/bootstrap?category=A").headers["ETag"]
        catalog_module.upsert_public_prices({("svc_ext", "A"): 91}, engine=engine)
        catalog_module.catalog_cache_clear()
        with _client() as client:
            after = client.get("/api/v1/bootstrap?category=A").headers["ETag"]
    finally:
        catalog_module.catalog_cache_clear()

    assert before != after


def test_bootstrap_staff_contact_reads_notification_settings(monkeypatch, tmp_path):
    from app.config import settings
    from app.db import init_db, make_engine
    from app.notifications import notification_cache_clear, upsert_booking_notification_settings

    db_url = f"sqlite+pysqlite:///{tmp_path / 'api-bootstrap-notifications.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    notification_cache_clear()
    upsert_booking_notification_settings(
        enabled=True,
        phone_number="+212 611 204 502",
        template_name="booking_alert",
        template_language="fr",
        engine=engine,
    )
    try:
        with _client() as client:
            body = client.get("/api/v1/bootstrap").json()
    finally:
        notification_cache_clear()

    TestCase().assertEqual(
        body["staff_contact"],
        {"whatsapp_phone": "+212611204502", "available": True},
    )


def test_bootstrap_logs_cache_status_for_200_and_304(caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")
    with _client() as client:
        first = client.get("/api/v1/bootstrap?category=A&promo=YS26")
        client.get(
            "/api/v1/bootstrap?category=A&promo=YS26",
            headers={"If-None-Match": first.headers["ETag"]},
        )

    messages = [rec.message for rec in caplog.records]
    assert any(
        "catalog.bootstrap category=A promo=YS26" in line
        and "has_services=true" in line
        and "cache_hit=200" in line
        and "duration_ms=" in line
        for line in messages
    )
    assert any(
        "catalog.bootstrap category=A promo=YS26" in line
        and "cache_hit=304" in line
        for line in messages
    )


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


def test_services_all_categories_match_catalog_pricing() -> None:
    expected_groups = {
        "A": {"wash": catalog.SERVICES_WASH, "detailing": catalog.SERVICES_DETAILING},
        "B": {"wash": catalog.SERVICES_WASH, "detailing": catalog.SERVICES_DETAILING},
        "C": {"wash": catalog.SERVICES_WASH, "detailing": catalog.SERVICES_DETAILING},
        "MOTO": {"moto": catalog.SERVICES_MOTO},
    }

    with _client() as client:
        for category, groups in expected_groups.items():
            response = client.get("/api/v1/catalog/services", params={"category": category})
            assert response.status_code == 200
            body = response.json()
            assert set(body) == set(groups)

            for bucket, services in groups.items():
                assert len(body[bucket]) == len(services)
                for item, service in zip(body[bucket], services):
                    service_id, name, desc, _prices = service
                    assert item == {
                        "id": service_id,
                        "name": name,
                        "desc": desc,
                        "price_dh": catalog.service_price(service_id, category),
                        "regular_price_dh": None,
                        "bucket": bucket,
                    }


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


# ── /catalog/centers ───────────────────────────────────────────────────────


def test_centers_endpoint_returns_active_static_center():
    with _client() as client:
        response = client.get("/api/v1/catalog/centers")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) >= 1
    # Static catalog seeds ctr_casa (Stand physique). DB additions append.
    casa = next((row for row in payload if row["id"] == "ctr_casa"), None)
    assert casa is not None
    assert casa["name"] == "Stand physique"
    assert "Bouskoura" in casa["details"]


def test_centers_endpoint_payload_shape_matches_pydantic_model():
    with _client() as client:
        payload = client.get("/api/v1/catalog/centers").json()
    for row in payload:
        assert set(row.keys()) == {"id", "name", "details"}
        assert isinstance(row["id"], str)
        assert isinstance(row["name"], str)
        assert isinstance(row["details"], str)


def test_centers_endpoint_logs_count(caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")
    with _client() as client:
        client.get("/api/v1/catalog/centers")
    assert any("catalog.centers listed count=" in rec.message for rec in caplog.records)


# ── /catalog/closed-dates ──────────────────────────────────────────────────


def test_closed_dates_endpoint_returns_static_eid_closures():
    with _client() as client:
        response = client.get("/api/v1/catalog/closed-dates")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    # Static catalog at the time of this test seeds the 2026 Eid al-Adha days.
    assert "2026-05-27" in payload
    assert "2026-05-28" in payload


def test_closed_dates_endpoint_sorted_ascending():
    with _client() as client:
        payload = client.get("/api/v1/catalog/closed-dates").json()
    assert payload == sorted(payload), f"closed dates returned unsorted: {payload}"


def test_closed_dates_endpoint_returns_only_iso_strings():
    import re

    iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    with _client() as client:
        payload = client.get("/api/v1/catalog/closed-dates").json()
    for item in payload:
        assert isinstance(item, str)
        assert iso_re.fullmatch(item), f"{item!r} is not a YYYY-MM-DD ISO date"


def test_closed_dates_endpoint_picks_up_db_added_closures(monkeypatch, tmp_path):
    """Admin-added closures from `closed_dates` table must appear in the
    response alongside the static catalog entries."""
    from app import catalog as catalog_module
    from app.config import settings
    from app.db import init_db, make_engine

    db_url = f"sqlite+pysqlite:///{tmp_path / 'api-closed-dates.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    catalog_module.upsert_closed_date(
        date_iso="2026-12-25", label="Noël (test)", active=True, engine=engine
    )
    monkeypatch.setattr(settings, "database_url", db_url)
    catalog_module.catalog_cache_clear()
    try:
        with _client() as client:
            payload = client.get("/api/v1/catalog/closed-dates").json()
        assert "2026-12-25" in payload
    finally:
        catalog_module.catalog_cache_clear()


def test_closed_dates_endpoint_logs_first_and_last(caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")
    with _client() as client:
        client.get("/api/v1/catalog/closed-dates")
    assert any(
        "catalog.closed_dates listed count=" in rec.message
        and "first=" in rec.message
        and "last=" in rec.message
        for rec in caplog.records
    )


# ── /catalog/time-slots ────────────────────────────────────────────────────


def test_time_slots_endpoint_without_date_returns_all_active():
    with _client() as client:
        response = client.get("/api/v1/catalog/time-slots")
    assert response.status_code == 200
    payload = response.json()
    # Static catalog seeds 6 slots (slot_9_11 through slot_20_22). The DB may
    # add or hide some; assert we get at least one and that they all match the
    # expected shape.
    assert len(payload) >= 1
    for row in payload:
        assert set(row.keys()) == {"id", "label", "period"}


def test_time_slots_endpoint_filters_using_2h_casablanca_cutoff():
    """A date with all slots in the past should return an empty list."""
    # 1996-01-01 is far enough in the past that every slot is filtered out
    # regardless of wall-clock skew. This pins the filter logic without
    # needing to mock the clock.
    with _client() as client:
        response = client.get("/api/v1/catalog/time-slots?date=1996-01-01")
    assert response.status_code == 200
    assert response.json() == []


def test_time_slots_endpoint_includes_far_future_slots():
    """A date in 2099 should return every active slot — none filtered out."""
    with _client() as client:
        all_slots = client.get("/api/v1/catalog/time-slots").json()
        future_slots = client.get("/api/v1/catalog/time-slots?date=2099-12-31").json()
    assert len(future_slots) == len(all_slots)
    assert {row["id"] for row in future_slots} == {row["id"] for row in all_slots}


def test_time_slots_endpoint_rejects_bad_date_format():
    with _client() as client:
        # Pydantic regex pattern rejects malformed dates at the boundary
        # before the handler is reached.
        response = client.get("/api/v1/catalog/time-slots?date=not-a-date")
    assert response.status_code == 422


def test_time_slots_helper_includes_slot_at_exact_2h_boundary():
    """The helper filter uses ``>=``, so a slot starting exactly 2h after now
    is INCLUDED. Pins the >= vs > boundary."""
    from datetime import datetime, timedelta
    from app.api import _slots_with_lead_filter
    from app.api_validation import CASABLANCA_TZ

    # Pin "now" to 07:00 on a date so slot_9_11 is exactly 2h ahead.
    now = datetime(2099, 6, 15, 7, 0, tzinfo=CASABLANCA_TZ)
    available, cutoff, _total = _slots_with_lead_filter(date_iso="2099-06-15", now=now)
    available_ids = {row.id for row in available}
    assert "slot_9_11" in available_ids
    assert cutoff == now + timedelta(hours=2)


def test_time_slots_helper_excludes_slot_strictly_before_cutoff():
    from datetime import datetime
    from app.api import _slots_with_lead_filter
    from app.api_validation import CASABLANCA_TZ

    # Pin "now" to 07:01 — slot_9_11 starts at 09:00, which is < 09:01 cutoff.
    now = datetime(2099, 6, 15, 7, 1, tzinfo=CASABLANCA_TZ)
    available, _cutoff, _total = _slots_with_lead_filter(date_iso="2099-06-15", now=now)
    available_ids = {row.id for row in available}
    assert "slot_9_11" not in available_ids
    # slot_11_13 is well past the cutoff.
    assert "slot_11_13" in available_ids


def test_time_slots_endpoint_logs_cutoff_when_date_supplied(caplog):
    caplog.set_level(logging.INFO, logger="ewash.api")
    with _client() as client:
        client.get("/api/v1/catalog/time-slots?date=2099-12-31")
    assert any(
        "catalog.time_slots listed date=2099-12-31" in rec.message
        and "cutoff=" in rec.message
        for rec in caplog.records
    )
