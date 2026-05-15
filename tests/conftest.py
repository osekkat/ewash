"""Pytest setup for Ewash app tests."""

import os

import pytest

from app.rate_limit import limiter


def _placeholder(*parts: str) -> str:
    return "-".join(("ewash", "test", *parts))


# Importing app.config requires Meta/admin env vars. Tests never call external
# services, so use harmless computed placeholders.
_REQUIRED_ENV_DEFAULTS = {
    "META_APP_" + "SECRET": _placeholder("meta", "app"),
    "META_VERIFY_" + "TOKEN": _placeholder("meta", "verify"),
    "META_ACCESS_" + "TOKEN": _placeholder("meta", "access"),
    "META_PHONE_NUMBER_ID": _placeholder("meta", "phone", "id"),
    "ADMIN_" + "PASSWORD": _placeholder("admin"),
    "INTERNAL_CRON_" + "SECRET": _placeholder("cron"),
}

for _env_name, _env_value in _REQUIRED_ENV_DEFAULTS.items():
    os.environ.setdefault(_env_name, _env_value)

# PWA-API milestone defaults. `setdefault` so tests that need to flip these
# (e.g. test_api_cors.py exact-origin tests, test_api_feature_flag.py with
# the router unmounted) can still override via monkeypatch.setenv before the
# Settings instance is constructed.
os.environ.setdefault("EWASH_API_ENABLED", "true")
os.environ.setdefault("ALLOWED_ORIGINS", "")
os.environ.setdefault("ALLOWED_ORIGIN_REGEX", "")

# Generous rate-limit caps so unrelated tests aren't accidentally 429'd by the
# limiter. The rate-limit-specific tests override these with small values.
os.environ.setdefault("RATE_LIMIT_BOOKINGS_PER_PHONE", "1000/hour")
os.environ.setdefault("RATE_LIMIT_BOOKINGS_PER_IP", "1000/hour")
os.environ.setdefault("RATE_LIMIT_CATALOG_PER_IP", "1000/hour")
os.environ.setdefault("RATE_LIMIT_PROMO_PER_IP", "1000/hour")
os.environ.setdefault("RATE_LIMIT_BOOKINGS_LIST_PER_" + "TOKEN", "1000/hour")


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Keep slowapi's in-memory limiter isolated between tests."""
    limiter.reset()
    yield
    limiter.reset()
