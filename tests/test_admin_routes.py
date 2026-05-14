from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.booking import Booking
import app.booking as booking_store
from app.config import settings
from app.db import init_db, make_engine, session_scope
from app.main import app
from app.models import ConversationSessionRow
from app.notifications import get_booking_notification_settings, notification_cache_clear
from app.persistence import _configured_engine, persist_confirmed_booking, persist_customer_bot_stage


def test_admin_entrypoint_defaults_to_french_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "")
    client = TestClient(app)

    response = client.get("/admin")

    assert response.status_code == 503
    assert "Portail admin non configuré" in response.text
    assert "ADMIN_PASSWORD" in response.text
    assert "Réservations" in response.text
    assert "Rappels" in response.text
    assert "?lang=en" in response.text


def test_admin_entrypoint_can_render_english_option_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "")
    client = TestClient(app)

    response = client.get("/admin?lang=en")

    assert response.status_code == 503
    assert "Admin portal is not configured" in response.text
    assert "ADMIN_PASSWORD" in response.text
    assert "Bookings" in response.text
    assert "Reminders" in response.text
    assert "?lang=fr" in response.text


def test_admin_entrypoint_shows_password_only_form_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)

    response = client.get("/admin")

    assert response.status_code == 200
    assert "Mot de passe" in response.text
    assert "name=\"password\"" in response.text
    assert "type=\"password\"" in response.text
    assert "Username" not in response.text
    assert "Nom d'utilisateur" not in response.text


def test_admin_entrypoint_rejects_wrong_password_without_username(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)

    response = client.post(
        "/admin",
        content="password=wrong-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert "Mot de passe incorrect" in response.text


def test_admin_entrypoint_accepts_configured_password_without_username(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)

    response = client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin"
    assert "ewash_admin_session" in response.headers["set-cookie"]

    dashboard = client.get("/admin")
    assert dashboard.status_code == 200
    assert "Tableau de bord" in dashboard.text
    assert "Mot de passe" not in dashboard.text
    assert "Version actuelle" in dashboard.text
    assert "Réservations aujourd" in dashboard.text
    assert "Rappels en attente" in dashboard.text
    assert "Aucune réservation persistée pour le moment" in dashboard.text
    assert "Réservations, clients, prix, promos et notifications" in dashboard.text
    assert "Pages réservations / clients / prix / promos" in dashboard.text
    assert "<span>OK</span>" in dashboard.text
    assert "class=\"metric-grid\"" in dashboard.text
    assert "class=\"empty-panel\"" in dashboard.text
    assert 'href="/admin/bookings"' in dashboard.text
    assert 'href="/admin/customers"' in dashboard.text
    assert 'href="/admin/prices"' in dashboard.text


def _sample_booking() -> Booking:
    booking = Booking(phone="212665883062")
    booking.name = "Sekkat"
    booking.vehicle_type = "B — Berline / SUV"
    booking.category = "B"
    booking.car_model = "Porsche"
    booking.color = "Gris"
    booking.service = "svc_cpl"
    booking.service_bucket = "wash"
    booking.service_label = "Le Complet — 125 DH"
    booking.price_dh = 125
    booking.price_regular_dh = 125
    booking.location_mode = "center"
    booking.center = "Stand physique — Mall Triangle Vert, Bouskoura · 7j/7 · 09h-22h30"
    booking.date_label = "Dimanche 26/04/2026"
    booking.slot = "09h – 11h"
    booking.assign_ref()
    return booking


def test_admin_bookings_page_renders_persisted_reservations(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-bookings.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    booking = _sample_booking()
    persist_confirmed_booking(booking, engine=engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.get("/admin/bookings")

    assert response.status_code == 200
    assert "Réservations" in response.text
    assert booking.ref in response.text
    assert "Sekkat" in response.text
    assert "Porsche" in response.text
    assert "Le Complet — 125 DH" in response.text
    assert "Dimanche 26/04/2026" in response.text
    assert "09h – 11h" in response.text
    assert "Cette page arrive dans le prochain lot" not in response.text
    _configured_engine.cache_clear()


def test_admin_bookings_page_includes_esthetique_addons_in_service_column(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-bookings-addons.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    booking = _sample_booking()
    booking.addon_service = "svc_pol"
    booking.addon_service_label = "Le Polissage — 963 DH (-10%)"
    booking.addon_price_dh = 963
    persist_confirmed_booking(booking, engine=engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.get("/admin/bookings")

    assert response.status_code == 200
    assert "Le Complet — 125 DH" in response.text
    assert "Esthétique : Le Polissage — 963 DH (-10%)" in response.text
    assert "1088 DH" in response.text
    _configured_engine.cache_clear()


def test_admin_customers_page_renders_persisted_clients(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-customers.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    booking = _sample_booking()
    persist_confirmed_booking(booking, engine=engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.get("/admin/customers")

    assert response.status_code == 200
    assert "Clients" in response.text
    assert "Sekkat" in response.text
    assert "212665883062" in response.text
    assert "Porsche — Gris" in response.text
    assert "1 réservation" in response.text
    assert "Cette page arrive dans le prochain lot" not in response.text
    _configured_engine.cache_clear()


def test_admin_customers_page_renders_last_whatsapp_stage_for_unconfirmed_leads(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-customer-stages.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    persist_customer_bot_stage("212600000003", "BOOK_SERVICE", engine=engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.get("/admin/customers")

    assert response.status_code == 200
    assert "212600000003" in response.text
    assert "Liste des prix affichée" in response.text
    assert "Étape WhatsApp" in response.text
    _configured_engine.cache_clear()


def test_admin_bookings_page_falls_back_to_live_memory_when_database_is_missing(monkeypatch):
    booking_store._bookings.clear()
    monkeypatch.setattr(booking_store, "_counter", 0)
    monkeypatch.setattr(settings, "database_url", "")
    _configured_engine.cache_clear()
    booking = _sample_booking()
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.get("/admin/bookings")

    assert response.status_code == 200
    assert "Mode temporaire" in response.text
    assert "Railway Postgres" in response.text
    assert booking.ref in response.text
    assert "Sam" not in response.text
    assert "Sekkat" in response.text
    assert "Porsche" in response.text
    booking_store._bookings.clear()
    _configured_engine.cache_clear()


def test_admin_customers_page_falls_back_to_live_memory_when_database_is_missing(monkeypatch):
    booking_store._bookings.clear()
    monkeypatch.setattr(booking_store, "_counter", 0)
    monkeypatch.setattr(settings, "database_url", "")
    _configured_engine.cache_clear()
    _sample_booking()
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.get("/admin/customers")

    assert response.status_code == 200
    assert "Mode temporaire" in response.text
    assert "Sekkat" in response.text
    assert "212665883062" in response.text
    assert "Porsche — Gris" in response.text
    assert "1 réservation" in response.text
    booking_store._bookings.clear()
    _configured_engine.cache_clear()


def test_admin_prices_page_renders_public_tariff(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.get("/admin/prices")

    assert response.status_code == 200
    assert "Prix" in response.text
    assert "Tarifs publics" in response.text
    assert "Lavages" in response.text
    assert "Esthétique" in response.text
    assert "L&#x27;Extérieur" in response.text
    assert "Le Complet" in response.text
    assert "Céramique 6m" in response.text
    assert "Scooter" in response.text
    assert "60 DH" in response.text
    assert "125 DH" in response.text
    assert "1150 DH" in response.text
    assert "105 DH" in response.text
    assert "Cette page arrive dans le prochain lot" not in response.text
    assert 'href="/admin/prices" class="active"' in response.text


def test_admin_prices_page_allows_updating_public_tariff(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-prices.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    import app.catalog as catalog
    catalog.catalog_cache_clear()
    notification_cache_clear()
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.post(
        "/admin/prices?lang=en",
        data={"price__svc_cpl__B": "131"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/prices?lang=en&saved=1"
    assert catalog.service_price("svc_cpl", "B") == 131
    updated = client.get(response.headers["location"])
    assert "131 DH" in updated.text
    assert "Prices saved" in updated.text
    catalog.catalog_cache_clear()
    _configured_engine.cache_clear()


def test_admin_promos_page_allows_adding_promo_codes(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-promos.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    import app.catalog as catalog
    catalog.catalog_cache_clear()
    notification_cache_clear()
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.post(
        "/admin/promos?lang=en",
        data={
            "code": "VIP30",
            "label": "VIP Thirty",
            "active": "on",
            "discount__svc_cpl__B": "90",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/promos?lang=en&saved=1"
    assert catalog.normalize_promo_code("vip30") == "VIP30"
    assert catalog.promo_label("VIP30") == "VIP Thirty"
    assert catalog.service_price("svc_cpl", "B", promo_code="VIP30") == 90
    page = client.get(response.headers["location"])
    assert "VIP30" in page.text
    assert "VIP Thirty" in page.text
    assert "90 DH" in page.text
    assert "Promos saved" in page.text
    catalog.catalog_cache_clear()
    _configured_engine.cache_clear()


def test_admin_promos_page_prefills_public_prices_for_number_steppers(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "")
    _configured_engine.cache_clear()
    import app.catalog as catalog
    catalog.catalog_cache_clear()
    notification_cache_clear()
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.get("/admin/promos")

    assert response.status_code == 200
    assert 'name="discount__svc_cpl__B" value="125"' in response.text
    assert 'data-public-price="125"' in response.text
    assert "Les tarifs publics sont préremplis" in response.text
    catalog.catalog_cache_clear()
    _configured_engine.cache_clear()


def test_admin_promos_submit_ignores_unchanged_public_price_prefills(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-promos-public-prefill.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    import app.catalog as catalog
    catalog.catalog_cache_clear()
    notification_cache_clear()
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.post(
        "/admin/promos?lang=en",
        data={
            "code": "PUBLIC",
            "label": "Public Price",
            "active": "on",
            "discount__svc_cpl__B": "125",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    promos = {promo.code: promo for promo in catalog.list_promo_codes()}
    assert promos["PUBLIC"].discounts == {}
    assert catalog.service_price("svc_cpl", "B", promo_code="PUBLIC") == 125
    catalog.catalog_cache_clear()
    _configured_engine.cache_clear()


def test_admin_remaining_tabs_are_real_operational_pages(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-ops-tabs.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    import app.catalog as catalog
    catalog.catalog_cache_clear()
    notification_cache_clear()
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    expected_pages = {
        "/admin/reminders": ("Rappels", "reminder_name"),
        "/admin/notifications": ("Notifications", "phone_number"),
        "/admin/closed-dates": ("Fermetures", "closed_date"),
        "/admin/time-slots": ("Créneaux", "slot_id"),
        "/admin/centers": ("Centres", "center_id"),
        "/admin/copy": ("Textes", "text_key"),
    }
    for path, (title, field_name) in expected_pages.items():
        response = client.get(path)
        assert response.status_code == 200
        assert title in response.text
        assert f'name="{field_name}"' in response.text
        assert "Cette page arrive dans le prochain lot" not in response.text
        assert f'href="{path}" class="active"' in response.text
    catalog.catalog_cache_clear()
    _configured_engine.cache_clear()


def test_admin_ops_pages_allow_updating_remaining_tabs(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-ops-updates.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    import app.catalog as catalog
    catalog.catalog_cache_clear()
    notification_cache_clear()
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    reminders = client.post(
        "/admin/reminders?lang=en",
        data={"reminder_name": "H-2", "offset_minutes_before": "120", "template_name": "booking_reminder_h2", "enabled": "on"},
        follow_redirects=False,
    )
    assert reminders.status_code == 303
    reminders_page = client.get(reminders.headers["location"])
    assert "H-2" in reminders_page.text
    assert "booking_reminder_h2" in reminders_page.text
    assert "Reminders saved" in reminders_page.text

    notifications = client.post(
        "/admin/notifications?lang=en",
        data={
            "enabled": "on",
            "phone_number": "+212 665 883 062",
            "template_name": "new_booking_alert",
            "template_language": "fr",
        },
        follow_redirects=False,
    )
    assert notifications.status_code == 303
    notification_config = get_booking_notification_settings()
    assert notification_config.enabled is True
    assert notification_config.phone_number == "212665883062"
    assert notification_config.template_name == "new_booking_alert"
    notifications_page = client.get(notifications.headers["location"])
    assert "212665883062" in notifications_page.text
    assert "new_booking_alert" in notifications_page.text
    assert "Notifications saved" in notifications_page.text
    assert "{{1}} type" in notifications_page.text

    closed = client.post(
        "/admin/closed-dates?lang=en",
        data={"closed_date": "2026-06-01", "label": "Maintenance", "active": "on"},
        follow_redirects=False,
    )
    assert closed.status_code == 303
    assert "2026-06-01" in catalog.active_closed_dates()
    assert "Maintenance" in client.get(closed.headers["location"]).text

    slot = client.post(
        "/admin/time-slots?lang=en",
        data={"slot_id": "slot_22_23", "label": "22h – 23h", "period": "Late", "active": "on"},
        follow_redirects=False,
    )
    assert slot.status_code == 303
    assert ("slot_22_23", "22h – 23h", "Late") in catalog.active_time_slots()
    assert "22h – 23h" in client.get(slot.headers["location"]).text

    center = client.post(
        "/admin/centers?lang=en",
        data={"center_id": "ctr_maarif", "name": "Maârif", "details": "Rue test · 09h-18h", "active": "on"},
        follow_redirects=False,
    )
    assert center.status_code == 303
    assert ("ctr_maarif", "Maârif", "Rue test · 09h-18h") in catalog.active_centers()
    assert "Maârif" in client.get(center.headers["location"]).text

    copy = client.post(
        "/admin/copy?lang=en",
        data={"text_key": "booking.welcome", "title": "Welcome", "body": "Bonjour from admin"},
        follow_redirects=False,
    )
    assert copy.status_code == 303
    snippets = {snippet.key: snippet for snippet in catalog.list_text_snippets()}
    assert snippets["booking.welcome"].body == "Bonjour from admin"
    assert "Bonjour from admin" in client.get(copy.headers["location"]).text

    catalog.catalog_cache_clear()
    notification_cache_clear()
    _configured_engine.cache_clear()


def test_admin_logout_clears_password_session(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    response = client.get("/admin/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin"
    assert "ewash_admin_session" in response.headers["set-cookie"]

    login = client.get("/admin")
    assert "Mot de passe" in login.text


def test_internal_conversation_abandon_endpoint_requires_secret_and_marks_stale_sessions(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'internal-abandon.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    persist_customer_bot_stage("212600000777", "MENU", engine=engine)
    with session_scope(engine) as session:
        conversation = session.scalars(select(ConversationSessionRow)).one()
        conversation.last_event_at = datetime.now(timezone.utc) - timedelta(hours=3)

    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(settings, "internal_cron_secret", "cron-secret")
    _configured_engine.cache_clear()
    client = TestClient(app)

    forbidden = client.post("/internal/conversations/abandon")
    response = client.post("/internal/conversations/abandon", headers={"X-Internal-Cron-Secret": "cron-secret"})

    assert forbidden.status_code == 403
    assert response.status_code == 200
    assert response.json() == {"abandoned": 1}
    with session_scope(engine) as session:
        conversation = session.scalars(select(ConversationSessionRow)).one()
        assert conversation.status == "abandoned"
    _configured_engine.cache_clear()
