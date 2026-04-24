from fastapi.testclient import TestClient

from app.main import APP_VERSION, app


def test_health_exposes_current_build_version():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": APP_VERSION}
