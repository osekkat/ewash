from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


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
    assert "Les pages opérationnelles arrivent dans les prochains lots" in dashboard.text
    assert "class=\"metric-grid\"" in dashboard.text
    assert "class=\"empty-panel\"" in dashboard.text


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
