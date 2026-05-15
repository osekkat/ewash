"""Rate limiting primitives for the planned /api/v1 surface."""
from __future__ import annotations

import hashlib
import logging
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from limits import parse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .security import hash_token

logger = logging.getLogger("ewash.rate_limit")

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
    headers_enabled=True,
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return the API's stable 429 envelope while preserving slowapi headers."""
    logger.info(
        "rate_limit.exceeded path=%s limit=%s",
        request.url.path,
        exc.detail,
    )
    response = JSONResponse(
        status_code=429,
        content={
            "error_code": "rate_limit_exceeded",
            "message": f"Rate limit exceeded: {exc.detail}",
        },
    )
    response.headers["X-Ewash-Error-Code"] = "rate_limit_exceeded"
    view_rate_limit = getattr(request.state, "view_rate_limit", None)
    if view_rate_limit is not None:
        response = request.app.state.limiter._inject_headers(response, view_rate_limit)
    return response


class PerPhoneRateLimitExceeded(HTTPException):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            status_code=429,
            detail={
                "error_code": "rate_limit_exceeded",
                "message": (
                    "Too many bookings from this phone. "
                    f"Retry after {retry_after_seconds} seconds."
                ),
                "scope": "per_phone",
            },
            headers={"Retry-After": str(retry_after_seconds)},
        )


def hit_phone_limit(phone: str, limit_str: str) -> None:
    """Consume one slot in the per-phone limiter for a normalized phone."""
    rule = parse(limit_str)
    key = f"phone:{_hash_phone(phone, length=16)}"
    if limiter.limiter.hit(rule, key):
        return

    stats = limiter.limiter.get_window_stats(rule, key)
    retry_after = max(1, int(stats.reset_time - time.time()))
    logger.info(
        "rate_limit.per_phone exceeded phone_hash=%s limit=%s retry_after=%d",
        _hash_phone(phone),
        limit_str,
        retry_after,
    )
    raise PerPhoneRateLimitExceeded(retry_after)


def _token_key_func(request: Request) -> str:
    """Hash customer tokens before using them as rate-limit keys."""
    token = request.headers.get("X-Ewash-Token", "")
    if token:
        return f"token:{hash_token(token)[:16]}"
    return get_remote_address(request)


def _hash_phone(phone: str, *, length: int = 12) -> str:
    return hashlib.sha256((phone or "").encode("utf-8")).hexdigest()[:length] if phone else "-"
