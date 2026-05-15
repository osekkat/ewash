"""PWA-facing /api/v1 router skeleton and shared error handling."""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from app import api_validation, catalog
from app.api_schemas import CategoryOut, ErrorResponse, ServiceOut
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


def _service_out(
    service: tuple,
    *,
    bucket: Literal["wash", "detailing", "moto"],
    category: Literal["A", "B", "C", "MOTO"],
    promo_code: str | None,
) -> ServiceOut:
    service_id, name, desc, _prices = service
    price = catalog.service_price(service_id, category, promo_code=promo_code)
    regular_price = catalog.service_price(service_id, category)
    return ServiceOut(
        id=service_id,
        name=name,
        desc=desc,
        price_dh=price or 0,
        regular_price_dh=regular_price if promo_code and price != regular_price else None,
        bucket=bucket,
    )


@router.get("/catalog/services", response_model=dict[str, list[ServiceOut]])
async def get_services(
    category: Literal["A", "B", "C", "MOTO"] = Query(...),
    promo: str | None = Query(None, max_length=40),
) -> dict[str, list[ServiceOut]]:
    """List bookable services with server-computed catalog pricing."""
    promo_code = catalog.normalize_promo_code(promo) if promo else None

    if category == "MOTO":
        result = {
            "moto": [
                _service_out(service, bucket="moto", category=category, promo_code=promo_code)
                for service in catalog.SERVICES_MOTO
            ]
        }
        logger.info(
            "catalog.services listed category=%s promo=%s count_moto=%d",
            category,
            promo_code or "-",
            len(result["moto"]),
        )
        return result

    result = {
        "wash": [
            _service_out(service, bucket="wash", category=category, promo_code=promo_code)
            for service in catalog.SERVICES_WASH
        ],
        "detailing": [
            _service_out(
                service,
                bucket="detailing",
                category=category,
                promo_code=promo_code,
            )
            for service in catalog.SERVICES_DETAILING
        ],
    }
    logger.info(
        "catalog.services listed category=%s promo=%s count_wash=%d count_detailing=%d",
        category,
        promo_code or "-",
        len(result["wash"]),
        len(result["detailing"]),
    )
    return result


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


# ── Catalog endpoints ────────────────────────────────────────────────────

def _build_category_payload() -> list[CategoryOut]:
    """Project the static VEHICLE_CATEGORIES tuples into the API contract.

    `id` uses the pricing-category key ("A" / "B" / "C" / "MOTO") because that
    is what the rest of the API takes (BookingCreateRequest.category, the
    service_price lookups). `label` uses the clean API-facing names from
    VEHICLE_CATEGORY_LABEL (the bot's list-row titles embed the letter prefix
    and an emoji, neither of which the PWA wants).
    """
    payload: list[CategoryOut] = []
    for row_id, _list_title, sub in catalog.VEHICLE_CATEGORIES:
        category_key = catalog.VEHICLE_CATEGORY_KEY.get(row_id)
        if category_key is None:
            # Defensive: a future row added to VEHICLE_CATEGORIES without a
            # corresponding VEHICLE_CATEGORY_KEY entry would otherwise leak
            # through with a missing id.
            logger.warning("catalog.categories skipping row=%s missing category key", row_id)
            continue
        label = catalog.VEHICLE_CATEGORY_LABEL.get(category_key, category_key)
        kind = "moto" if category_key == catalog.MOTO_PRICE_CATEGORY else "car"
        payload.append(CategoryOut(id=category_key, label=label, sub=sub, kind=kind))
    return payload


@router.get("/catalog/categories", response_model=list[CategoryOut])
async def list_catalog_categories() -> list[CategoryOut]:
    """Vehicle categories: 3 car tiers + Moto/Scooter."""
    categories = _build_category_payload()
    logger.info("catalog.categories listed count=%d", len(categories))
    return categories


__all__ = [
    "_DOMAIN_EXC_MAP",
    "api_exception_handler",
    "domain_error_response",
    "install_exception_handlers",
    "list_catalog_categories",
    "router",
]
