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
