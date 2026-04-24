"""Pytest setup for Ewash app tests."""

import os

# Importing app.config requires Meta env vars. Tests never call Meta, so use
# harmless placeholders.
os.environ.setdefault("META_APP_SECRET", "test-secret")
os.environ.setdefault("META_VERIFY_TOKEN", "test-verify-token")
os.environ.setdefault("META_ACCESS_TOKEN", "test-access-token")
os.environ.setdefault("META_PHONE_NUMBER_ID", "test-phone-number-id")
