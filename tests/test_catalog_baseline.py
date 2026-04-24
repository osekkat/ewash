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
