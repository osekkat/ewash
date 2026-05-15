"""Tests for app.security — token generation + SHA-256 hashing."""
from __future__ import annotations

import re

import pytest

from app import security


URL_SAFE_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


def test_generate_token_default_shape():
    plaintext, digest = security.generate_token()
    # 32 random bytes → 43 url-safe base64 chars (no padding).
    assert len(plaintext) == 43
    assert URL_SAFE_RE.fullmatch(plaintext)
    # SHA-256 hex digest is always 64 lowercase hex chars.
    assert HEX_64_RE.fullmatch(digest)


def test_generate_token_pair_round_trips():
    plaintext, digest = security.generate_token()
    assert security.hash_token(plaintext) == digest


def test_generate_token_returns_distinct_values_across_many_calls():
    seen_plaintexts: set[str] = set()
    seen_digests: set[str] = set()
    for _ in range(1000):
        plaintext, digest = security.generate_token()
        seen_plaintexts.add(plaintext)
        seen_digests.add(digest)
    # Astronomically unlikely to collide on 256-bit entropy.
    assert len(seen_plaintexts) == 1000
    assert len(seen_digests) == 1000


def test_hash_token_is_stable_for_same_input():
    plaintext = "the-quick-brown-fox-jumps-over-the-lazy-dog"
    assert security.hash_token(plaintext) == security.hash_token(plaintext)
    # Known SHA-256 for that exact ASCII string.
    assert (
        security.hash_token(plaintext)
        == "952a845f1e32a56fb2ec38ff36baae03a5e588ffd882ba88f42d6791b34c214b"
    )


def test_hash_token_changes_with_any_input_change():
    digest_a = security.hash_token("token-A")
    digest_b = security.hash_token("token-B")
    digest_a_trailing_space = security.hash_token("token-A ")
    assert digest_a != digest_b
    assert digest_a != digest_a_trailing_space


def test_hash_token_handles_unicode():
    # UTF-8 encoding is fixed inside hash_token — non-ASCII inputs must be
    # accepted without raising and produce a stable 64-char hex.
    digest = security.hash_token("café-☕")
    assert HEX_64_RE.fullmatch(digest)


def test_generate_token_respects_custom_byte_length():
    plaintext, digest = security.generate_token(byte_length=48)
    # token_urlsafe(48) → 64 chars (no padding).
    assert len(plaintext) == 64
    assert HEX_64_RE.fullmatch(digest)
    assert security.hash_token(plaintext) == digest


def test_generate_token_rejects_dangerously_short_byte_length():
    with pytest.raises(ValueError, match="at least 16"):
        security.generate_token(byte_length=8)
