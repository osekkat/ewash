"""Security primitives for the Ewash API surface.

Currently exposes the SHA-256 + url-safe random token pair used to mint and
verify customer `bookings_token` values. Tokens are 256-bit random secrets
that authenticate read access to a customer's own bookings without requiring
OTP or password. Plaintext is returned exactly once to the PWA; only the
SHA-256 digest is persisted in `customer_tokens.token_hash`.
"""
from __future__ import annotations

import hashlib
import secrets


def generate_token(*, byte_length: int = 32) -> tuple[str, str]:
    """Return a fresh ``(plaintext, sha256_hex)`` pair for a new customer token.

    The plaintext is a URL-safe base64 string with ~256 bits of entropy
    (43 chars for the default 32-byte input). The hash is 64 hex characters,
    sized to fit cleanly in the ``VARCHAR(64)`` column declared by migration
    0006 (``customer_tokens.token_hash``).
    """
    if byte_length < 16:
        raise ValueError("byte_length must be at least 16 (128-bit entropy)")
    plaintext = secrets.token_urlsafe(byte_length)
    return plaintext, hash_token(plaintext)


def hash_token(plaintext: str) -> str:
    """Stable SHA-256 hex digest of the plaintext token.

    Used for DB lookups: callers compare ``token_hash`` to
    ``hash_token(submitted_plaintext)``. The digest is deterministic and
    constant-time-comparable. The empty string hashes to a fixed digest; the
    caller is responsible for rejecting empty plaintexts before lookup.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
