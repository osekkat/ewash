"""Tests for ``app.config.Settings``.

``conftest.py`` sets a few env vars so the rest of the suite can boot the
FastAPI app cleanly (ADMIN_PASSWORD, EWASH_API_ENABLED, generous rate limits,
etc.). The class-default tests below clear the relevant env vars first via
``monkeypatch.delenv(..., raising=False)`` and instantiate a fresh
``Settings()`` so they really do exercise the Pydantic-level defaults rather
than the conftest values."""
from app.config import Settings


def _clear_env(monkeypatch, *names: str) -> None:
    for n in names:
        monkeypatch.delenv(n, raising=False)


def test_v03_admin_and_database_settings_have_safe_defaults(monkeypatch):
    _clear_env(
        monkeypatch,
        "DATABASE_URL",
        "ADMIN_PASSWORD",
        "ADMIN_SESSION_SECRET",
        "INTERNAL_CRON_SECRET",
        "ADMIN_DEFAULT_LOCALE",
    )
    s = Settings()
    assert s.database_url == ""
    assert s.admin_password == ""
    assert s.admin_session_secret == ""
    assert s.admin_session_ttl_seconds == 604800
    assert s.internal_cron_secret == ""
    assert s.admin_default_locale == "fr"


def test_api_v1_defaults_are_permissive_for_local_dev(monkeypatch):
    _clear_env(
        monkeypatch,
        "ALLOWED_ORIGINS",
        "ALLOWED_ORIGIN_REGEX",
        "EWASH_API_ENABLED",
        "API_ENABLED",
        "RATE_LIMIT_BOOKINGS_PER_PHONE",
        "RATE_LIMIT_BOOKINGS_PER_IP",
        "RATE_LIMIT_PROMO_PER_IP",
        "RATE_LIMIT_BOOKINGS_LIST_PER_TOKEN",
    )
    s = Settings()
    assert s.allowed_origins == ""
    assert s.allowed_origin_regex == ""
    assert s.allowed_origins_list() == []
    assert s.api_enabled
    assert s.rate_limit_bookings_per_phone == "5/hour"
    assert s.rate_limit_bookings_per_ip == "20/hour"
    assert s.rate_limit_promo_per_ip == "60/hour"
    assert s.rate_limit_bookings_list_per_token == "60/hour"


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
    # API_ENABLED would otherwise win if conftest set it; clear both to be sure.
    monkeypatch.delenv("API_ENABLED", raising=False)
    monkeypatch.setenv("EWASH_API_ENABLED", "false")
    s = Settings()
    assert not s.api_enabled


def test_api_enabled_disabled_via_unprefixed_alias(monkeypatch):
    # The EWASH_-prefixed alias has priority in AliasChoices; clear it so the
    # unprefixed alias can drive the value.
    monkeypatch.delenv("EWASH_API_ENABLED", raising=False)
    monkeypatch.setenv("API_ENABLED", "false")
    s = Settings()
    assert not s.api_enabled
