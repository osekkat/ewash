"""PWA-facing /api/v1 router skeleton and shared error handling."""
from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from app import api_validation
from app.api_schemas import ErrorResponse
from app.notifications import InvalidPhone

logger = logging.getLogger("ewash.api")

router = APIRouter(
    prefix="/api/v1",
    tags=["pwa-api"],
)

_DOMAIN_EXC_MAP: dict[type[Exception], tuple[int, str]] = {
    api_validation.ClosedDate: (400, api_validation.ClosedDate.error_code),
    api_validation.UnknownSlot: (400, api_validation.UnknownSlot.error_code),
    api_validation.SlotTooSoon: (400, api_validation.SlotTooSoon.error_code),
    api_validation.InvalidDate: (400, api_validation.InvalidDate.error_code),
    api_validation.UnknownService: (400, api_validation.UnknownService.error_code),
    api_validation.InvalidServiceForCategory: (
        400,
        api_validation.InvalidServiceForCategory.error_code,
    ),
    api_validation.UnknownAddon: (400, api_validation.UnknownAddon.error_code),
    api_validation.DuplicateAddon: (400, api_validation.DuplicateAddon.error_code),
    api_validation.NotADetailingService: (
        400,
        api_validation.NotADetailingService.error_code,
    ),
    api_validation.UnknownCenter: (400, api_validation.UnknownCenter.error_code),
    api_validation.MissingCenterId: (400, api_validation.MissingCenterId.error_code),
    api_validation.CenterIdNotAllowed: (
        400,
        api_validation.CenterIdNotAllowed.error_code,
    ),
    InvalidPhone: (400, InvalidPhone.error_code),
}


def _json_error(status_code: int, code: str, message: str) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error_code=code, message=message).model_dump(),
    )
    response.headers["X-Ewash-Error-Code"] = code
    return response


def domain_error_response(exc: Exception) -> JSONResponse:
    """Convert a known domain exception into the stable PWA error envelope."""
    status_code, code = _DOMAIN_EXC_MAP.get(type(exc), (500, "internal_error"))
    logger.info(
        "ewash.api domain_error type=%s status=%d error_code=%s",
        type(exc).__name__,
        status_code,
        code,
    )
    return _json_error(status_code, code, str(exc))


async def api_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI exception handler shared by all /api/v1 routes."""
    if type(exc) in _DOMAIN_EXC_MAP:
        return domain_error_response(exc)

    logger.exception("ewash.api unhandled exception path=%s", request.url.path)
    return _json_error(500, "internal_error", "")


def install_exception_handlers(app: FastAPI) -> None:
    """Register API exception handling on the FastAPI application.

    FastAPI's APIRouter has no exception-handler decorator, so app/main.py will
    call this after including the router in a later integration bead.
    """
    app.add_exception_handler(Exception, api_exception_handler)


__all__ = [
    "_DOMAIN_EXC_MAP",
    "api_exception_handler",
    "domain_error_response",
    "install_exception_handlers",
    "router",
]
