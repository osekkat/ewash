"""Pytest setup for Ewash app tests."""

import os

# Importing app.config requires Meta env vars. Tests never call Meta, so use
# harmless placeholders.
os.environ.setdefault("META_APP_SECRET", "test-secret")
os.environ.setdefault("META_VERIFY_TOKEN", "test-verify-token")
os.environ.setdefault("META_ACCESS_TOKEN", "test-access-token")
os.environ.setdefault("META_PHONE_NUMBER_ID", "test-phone-number-id")

# Admin + internal-cron secrets — used by `/admin` route tests and
# `/internal/conversations/abandon` tests respectively.
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("INTERNAL_CRON_SECRET", "test-cron-secret")

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
os.environ.setdefault("RATE_LIMIT_PROMO_PER_IP", "1000/hour")
os.environ.setdefault("RATE_LIMIT_BOOKINGS_LIST_PER_TOKEN", "1000/hour")
