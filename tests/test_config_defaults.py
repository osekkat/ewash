from app.config import settings


def test_v03_admin_and_database_settings_have_safe_defaults():
    assert settings.database_url == ""
    assert settings.admin_password == ""
    assert settings.admin_session_secret == ""
    assert settings.admin_session_ttl_seconds == 604800
    assert settings.internal_cron_secret == ""
    assert settings.admin_default_locale == "fr"
