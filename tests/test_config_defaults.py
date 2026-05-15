from app.config import Settings, settings


def test_v03_admin_and_database_settings_have_safe_defaults():
    assert settings.database_url == ""
    assert settings.admin_password == ""
    assert settings.admin_session_secret == ""
    assert settings.admin_session_ttl_seconds == 604800
    assert settings.internal_cron_secret == ""
    assert settings.admin_default_locale == "fr"


def test_api_v1_defaults_are_permissive_for_local_dev():
    assert settings.allowed_origins == ""
    assert settings.allowed_origin_regex == ""
    assert settings.allowed_origins_list() == []
    assert settings.api_enabled
    assert settings.rate_limit_bookings_per_phone == "5/hour"
    assert settings.rate_limit_bookings_per_ip == "20/hour"
    assert settings.rate_limit_promo_per_ip == "60/hour"
    assert settings.rate_limit_bookings_list_per_token == "60/hour"


def test_allowed_origins_list_parses_comma_separated(monkeypatch):
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "https://a.com, https://b.com ,https://c.com",
    )
    s = Settings()
    assert s.allowed_origins_list() == [
        "https://a.com",
        "https://b.com",
        "https://c.com",
    ]


def test_allowed_origins_list_drops_empty_segments(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", ",,https://only.com,,")
    s = Settings()
    assert s.allowed_origins_list() == ["https://only.com"]


def test_api_enabled_disabled_via_ewash_prefix(monkeypatch):
    monkeypatch.setenv("EWASH_API_ENABLED", "false")
    s = Settings()
    assert not s.api_enabled


def test_api_enabled_disabled_via_unprefixed_alias(monkeypatch):
    monkeypatch.setenv("API_ENABLED", "false")
    s = Settings()
    assert not s.api_enabled
