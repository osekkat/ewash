"""Tests for app.admin._source_badge — booking source HTML badge helper."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.booking import Booking
from app.admin import _SOURCE_BADGES, _source_badge
from app.config import settings
from app.db import init_db, make_engine, session_scope
from app.main import app
from app.persistence import _configured_engine, admin_dashboard_summary, persist_confirmed_booking


def _strip_tags(html_snippet: str) -> str:
    return re.sub(r"<[^>]+>", "", html_snippet)


def _booking(ref: str, *, phone: str = "212665883062", name: str = "Sekkat") -> Booking:
    booking = Booking(phone=phone)
    booking.name = name
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
    booking.center = "Stand physique — Mall Triangle Vert, Bouskoura"
    booking.date_label = "Dimanche 26/04/2026"
    booking.date_iso = "2026-04-26"
    booking.slot = "09h – 11h"
    booking.slot_id = "slot_9_11"
    booking.ref = ref
    return booking


def _persist_source_booking(engine, ref: str, source: str, *, created_at: datetime | None = None) -> None:
    index = int(ref.rsplit("-", 1)[-1])
    booking = _booking(
        ref,
        phone=f"21266588{index:04d}",
        name=f"Client {index}",
    )
    row = persist_confirmed_booking(booking, source=source, engine=engine)
    if created_at is not None:
        with session_scope(engine) as session:
            saved = session.get(type(row), row.id)
            saved.created_at = created_at


def _admin_client(monkeypatch, db_url: str) -> TestClient:
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    monkeypatch.setattr(settings, "admin_password", "secret-pass")
    client = TestClient(app)
    client.post(
        "/admin",
        content="password=secret-pass",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    return client


def _metric_value(html: str, label: str) -> int:
    label_index = html.index(label)
    start = html.rfind('<article class="metric-card">', 0, label_index)
    end = html.index("</article>", label_index)
    card = html[start:end]
    match = re.search(r'<div class="metric-value">(\d+)</div>', card)
    assert match is not None
    return int(match.group(1))


def test_source_badge_whatsapp_french():
    snippet = _source_badge("whatsapp", locale="fr")
    assert 'class="badge src-wa"' in snippet
    assert 'title="whatsapp"' in snippet
    assert "📱" in snippet
    assert "WhatsApp" in _strip_tags(snippet)


def test_source_badge_api_french():
    snippet = _source_badge("api", locale="fr")
    assert 'class="badge src-pwa"' in snippet
    assert 'title="api"' in snippet
    assert "🌐" in snippet
    assert "PWA" in _strip_tags(snippet)


def test_source_badge_admin_french():
    snippet = _source_badge("admin", locale="fr")
    assert 'class="badge src-admin"' in snippet
    assert 'title="admin"' in snippet
    assert "👤" in snippet
    assert "Admin" in _strip_tags(snippet)


def test_source_badge_english_locale_renders_same_labels():
    # The three sources happen to share French + English labels today; the
    # test still pins the contract so a future French rename doesn't silently
    # leak into the English admin.
    snippet = _source_badge("api", locale="en")
    assert "PWA" in _strip_tags(snippet)


def test_source_badge_none_defaults_to_whatsapp():
    # Legacy rows persisted before the `source` column existed are stored as
    # NULL/empty. They render as WhatsApp (the only channel that existed).
    snippet = _source_badge(None)
    assert "src-wa" in snippet
    assert "📱" in snippet


def test_source_badge_empty_string_defaults_to_whatsapp():
    snippet = _source_badge("")
    assert "src-wa" in snippet


def test_source_badge_unknown_source_falls_back_to_whatsapp_label():
    # The CSS class falls back too, so an unexpected `source` value can't
    # render with no styling and break the table layout.
    snippet = _source_badge("zapier")
    assert "src-wa" in snippet
    assert "WhatsApp" in _strip_tags(snippet)


def test_source_badge_escapes_unknown_source_in_attribute():
    # XSS defense: the raw `source` value flows into the title= attribute and
    # must be HTML-escaped. The label text path falls back to the WhatsApp
    # display, so injection through the visible label is mechanically
    # impossible — but the attribute is the realistic vector.
    snippet = _source_badge('"><script>alert(1)</script>')
    assert "<script>" not in snippet
    assert "&lt;script&gt;" in snippet or "&quot;" in snippet


def test_source_badge_registry_contains_three_sources():
    # Pin the public registry — additions force a conscious choice about
    # CSS class + emoji per new source.
    assert set(_SOURCE_BADGES.keys()) == {"whatsapp", "api", "admin"}


def test_bookings_table_renders_badges_for_each_source(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-source-bookings.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    for source, suffix in (("whatsapp", "0001"), ("api", "0002"), ("admin", "0003")):
        _persist_source_booking(engine, f"EW-2026-{suffix}", source)

    client = _admin_client(monkeypatch, db_url)
    response = client.get("/admin/bookings")

    assert response.status_code == 200
    assert "badge src-wa" in response.text
    assert "badge src-pwa" in response.text
    assert "badge src-admin" in response.text
    assert "📱" in response.text
    assert "🌐" in response.text
    assert "👤" in response.text
    _configured_engine.cache_clear()


def test_dashboard_recent_bookings_renders_badges_for_each_source(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-source-dashboard.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    for source, suffix in (("whatsapp", "0011"), ("api", "0012"), ("admin", "0013")):
        _persist_source_booking(engine, f"EW-2026-{suffix}", source)

    client = _admin_client(monkeypatch, db_url)
    response = client.get("/admin")

    assert response.status_code == 200
    assert "Client 11" in response.text
    assert "Client 12" in response.text
    assert "Client 13" in response.text
    assert "badge src-wa" in response.text
    assert "badge src-pwa" in response.text
    assert "badge src-admin" in response.text
    _configured_engine.cache_clear()


def test_dashboard_split_counters(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-source-counters.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    for i in range(3):
        _persist_source_booking(engine, f"EW-2026-01{i}", "whatsapp")
    for i in range(5):
        _persist_source_booking(engine, f"EW-2026-02{i}", "api")

    client = _admin_client(monkeypatch, db_url)
    response = client.get("/admin")

    assert response.status_code == 200
    assert _metric_value(response.text, "Réservations PWA (7j)") == 5
    assert _metric_value(response.text, "Réservations WhatsApp (7j)") == 3
    _configured_engine.cache_clear()


def test_dashboard_counters_respect_7d_window(tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-source-window.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    now = datetime.now(timezone.utc)
    _persist_source_booking(engine, "EW-2026-0301", "api", created_at=now)
    _persist_source_booking(engine, "EW-2026-0302", "api", created_at=now - timedelta(days=10))

    summary = admin_dashboard_summary(engine=engine)

    assert summary.bookings_pwa_last_7d == 1
    assert summary.bookings_whatsapp_last_7d == 0


def test_admin_dashboard_summary_includes_source_breakdown(tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin-source-summary.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    _persist_source_booking(engine, "EW-2026-0401", "whatsapp")
    _persist_source_booking(engine, "EW-2026-0402", "api")
    _persist_source_booking(engine, "EW-2026-0403", "admin")

    summary = admin_dashboard_summary(engine=engine)

    assert summary.bookings_whatsapp_last_7d == 1
    assert summary.bookings_pwa_last_7d == 1
    assert summary.bookings_admin_last_7d == 1
