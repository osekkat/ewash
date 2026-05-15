from app import catalog


def test_current_yasmine_promo_baseline_prices():
    assert catalog.normalize_promo_code("  ys26  ") == "YS26"
    assert catalog.normalize_promo_code("HPL25") is None
    assert catalog.normalize_promo_code("YASMINE") is None

    assert catalog.service_price("svc_cpl", "B") == 125
    assert catalog.service_price("svc_cpl", "B", promo_code="YS26") == 110
    assert catalog.service_price("svc_moto", "MOTO", promo_code="YS26") == 105


def test_whatsapp_catalog_rows_respect_title_and_description_caps():
    for category in ["A", "B", "C"]:
        for bucket in ["wash", "detailing"]:
            for promo_code in [None, "YS26"]:
                rows = catalog.build_car_service_rows(category, bucket=bucket, promo_code=promo_code)
                assert rows
                for _row_id, title, description in rows:
                    assert len(title) <= 24
                    assert len(description) <= 72

    for _row_id, title, description in catalog.build_moto_service_rows():
        assert len(title) <= 24
        assert len(description) <= 72


def test_database_overrides_public_prices_and_promo_codes(monkeypatch, tmp_path):
    from app.db import init_db, make_engine, session_scope
    from app.config import settings
    from app.models import PromoCodeRow, PromoDiscountRow, ServicePriceRow

    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog-admin.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    with session_scope(engine) as session:
        session.add(ServicePriceRow(service_id="svc_cpl", category="B", price_dh=130))
        session.add(PromoCodeRow(code="VIP30", label="VIP Thirty", active=True))
        session.flush()
        session.add(PromoDiscountRow(promo_code="VIP30", service_id="svc_cpl", category="B", price_dh=90))

    monkeypatch.setattr(settings, "database_url", db_url)
    catalog.catalog_cache_clear()
    try:
        assert catalog.service_price("svc_cpl", "B") == 130
        assert catalog.normalize_promo_code(" vip30 ") == "VIP30"
        assert catalog.promo_label("VIP30") == "VIP Thirty"
        assert catalog.service_price("svc_cpl", "B", promo_code="VIP30") == 90
        rows = catalog.build_car_service_rows("B", bucket="wash", promo_code="VIP30")
        assert any(row_id == "svc_cpl" and "90 DH" in title for row_id, title, _desc in rows)
    finally:
        catalog.catalog_cache_clear()


def test_service_label_basic():
    assert catalog.service_label("svc_cpl", "B") == "Le Complet — 125 DH"


def test_service_label_with_promo():
    assert catalog.service_label("svc_cpl", "B", promo_code="YS26") == "Le Complet — 110 DH"


def test_service_label_moto():
    assert catalog.service_label("svc_moto", "MOTO") == "Moto — 105 DH"
    assert catalog.service_label("svc_scooter", "MOTO") == "Scooter — 85 DH"


def test_service_label_unknown_returns_id_only():
    # Unknown service id → service_name returns the id, service_price returns None.
    assert catalog.service_label("svc_nope", "B") == "svc_nope"


def test_vehicle_label_car_with_make():
    assert catalog.vehicle_label("A", make="Clio") == "Citadine (Clio)"
    assert catalog.vehicle_label("B", make="Megane") == "Berline / SUV (Megane)"


def test_vehicle_label_car_without_make():
    assert catalog.vehicle_label("A") == "Citadine"
    assert catalog.vehicle_label("C") == "Grande berline/SUV"


def test_vehicle_label_moto_never_takes_make():
    assert catalog.vehicle_label("MOTO") == "Moto/Scooter"
    # Moto bookings don't carry a model — make is ignored.
    assert catalog.vehicle_label("MOTO", make="MT-07") == "Moto/Scooter"


def test_vehicle_label_unknown_category_passes_through():
    assert catalog.vehicle_label("Z") == "Z"


def test_location_label_home():
    assert catalog.location_label("home") == "À domicile"


def test_location_label_center_uses_active_centers():
    # The default static center "ctr_casa" has name "Stand physique" — the
    # helper must not prefix "Stand " again.
    label = catalog.location_label("center", center_id="ctr_casa")
    assert label == "Stand physique"


def test_location_label_center_prefixes_when_missing():
    from app.db import init_db, make_engine
    from app.config import settings

    # Insert a center whose name does NOT start with "Stand " and verify the
    # helper prefixes it.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_url = f"sqlite+pysqlite:///{tmp_dir}/center-label.db"
        engine = make_engine(db_url)
        init_db(engine)
        catalog.upsert_center(
            center_id="ctr_marina",
            name="Marina Bouskoura",
            details="…",
            active=True,
            sort_order=1,
            engine=engine,
        )
        previous = settings.database_url
        settings.database_url = db_url
        catalog.catalog_cache_clear()
        try:
            assert catalog.location_label("center", center_id="ctr_marina") == "Stand Marina Bouskoura"
        finally:
            settings.database_url = previous
            catalog.catalog_cache_clear()


def test_location_label_center_unknown_falls_back():
    assert catalog.location_label("center", center_id="ctr_nope") == "Au stand"
    assert catalog.location_label("center") == "Au stand"


def test_location_label_passthrough_for_unknown_kind():
    assert catalog.location_label("unspecified") == "unspecified"


def test_compute_catalog_etag_seed_static_when_no_db(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "database_url", "")
    catalog.catalog_cache_clear()
    try:
        assert catalog.compute_catalog_etag_seed() == "static-v1"
    finally:
        catalog.catalog_cache_clear()


def test_compute_catalog_etag_seed_changes_after_admin_edit(monkeypatch, tmp_path):
    from app.db import init_db, make_engine
    from app.config import settings

    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog-etag.db'}"
    engine = make_engine(db_url)
    init_db(engine)  # seeds the `services` table → seed is real, not "static-v1"

    monkeypatch.setattr(settings, "database_url", db_url)
    catalog.catalog_cache_clear()
    try:
        seed_at_baseline = catalog.compute_catalog_etag_seed()
        assert seed_at_baseline  # non-empty
        assert seed_at_baseline != "static-v1"  # services seeded at init_db

        # An admin edit on a different table must shift the seed.
        import time
        time.sleep(0.01)  # ensure monotonic timestamp tick at SQLite's resolution
        catalog.upsert_public_prices({("svc_cpl", "B"): 999}, engine=engine)
        seed_after_price = catalog.compute_catalog_etag_seed()
        assert seed_after_price != seed_at_baseline

        time.sleep(0.01)
        catalog.upsert_text_snippet(
            key="booking.note",
            title="Note",
            body="Une note ?",
            engine=engine,
        )
        seed_after_text = catalog.compute_catalog_etag_seed()
        assert seed_after_text != seed_after_price
    finally:
        catalog.catalog_cache_clear()
