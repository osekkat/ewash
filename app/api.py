"""PWA-facing /api/v1 router skeleton and shared error handling."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from app import api_validation, catalog
from app.api_schemas import (
    CategoryOut,
    CenterOut,
    ErrorResponse,
    PromoValidateRequest,
    PromoValidateResponse,
    ServiceOut,
    TimeSlotOut,
)
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


@router.get("/catalog/centers", response_model=list[CenterOut])
async def list_catalog_centers() -> list[CenterOut]:
    """Active stand/center options for the location-picker step."""
    centers = [
        CenterOut(id=center_id, name=name, details=details or "")
        for center_id, name, details in catalog.active_centers()
    ]
    logger.info("catalog.centers listed count=%d", len(centers))
    return centers


_SLOT_HOUR_RE = re.compile(r"^slot_(\d+)_\d+$")


def _slots_with_lead_filter(
    *,
    date_iso: str | None,
    now: datetime | None = None,
) -> tuple[list[TimeSlotOut], datetime | None, int]:
    """Return (payload, cutoff, total_count).

    When `date_iso` is None: return every active slot, no filtering.
    When supplied: filter to slots whose start time is >= now + 2h in
    Africa/Casablanca. `now` is injectable for tests.
    """
    all_slots = catalog.active_time_slots()
    if date_iso is None:
        return (
            [TimeSlotOut(id=slot_id, label=label, period=period) for slot_id, label, period in all_slots],
            None,
            len(all_slots),
        )

    try:
        appointment_date = datetime.strptime(date_iso, "%Y-%m-%d").date()
    except ValueError as exc:
        raise api_validation.InvalidDate(f"date={date_iso} not parseable") from exc

    if now is None:
        now_tz = datetime.now(tz=api_validation.CASABLANCA_TZ)
    else:
        now_tz = now.astimezone(api_validation.CASABLANCA_TZ)
    cutoff = now_tz + timedelta(hours=api_validation.MIN_LEAD_HOURS)

    available: list[TimeSlotOut] = []
    for slot_id, label, period in all_slots:
        match = _SLOT_HOUR_RE.match(slot_id)
        if match is None:
            # Skip malformed slot ids defensively — `validate_slot_and_date`
            # is the authoritative gate for booking submissions.
            continue
        start_hour = int(match.group(1))
        candidate = datetime(
            appointment_date.year,
            appointment_date.month,
            appointment_date.day,
            start_hour,
            0,
            tzinfo=api_validation.CASABLANCA_TZ,
        )
        if candidate >= cutoff:
            available.append(TimeSlotOut(id=slot_id, label=label, period=period))
    return available, cutoff, len(all_slots)


@router.get("/catalog/time-slots", response_model=list[TimeSlotOut])
async def list_catalog_time_slots(
    date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> list[TimeSlotOut]:
    """Slot rows for the booking flow. Optional `date=YYYY-MM-DD` filters out
    slots starting <2h after server-side `now` in Africa/Casablanca.

    The PWA's client-side 2-hour filter is decorative — a user with a
    tampered clock or wrong timezone could otherwise submit a slot in the
    past. This endpoint is the authoritative source.
    """
    available, cutoff, total = _slots_with_lead_filter(date_iso=date)
    logger.info(
        "catalog.time_slots listed date=%s total=%d returned=%d cutoff=%s",
        date or "-",
        total,
        len(available),
        cutoff.isoformat() if cutoff else "-",
    )
    return available


# ── Promo validation ──────────────────────────────────────────────────────


def _build_promo_discount_map(code: str, category: str) -> dict[str, int]:
    """Return ``{service_id: discounted_price}`` for every service whose
    discounted price under ``code`` is strictly less than the public price.

    Services that aren't in the partner's discount grid (or whose discount
    equals the public price) are omitted so the PWA only renders
    strike-through pricing where there's actually a saving to show.
    """
    if category == catalog.MOTO_PRICE_CATEGORY:
        services = catalog.SERVICES_MOTO
    else:
        services = catalog.SERVICES_CAR
    prices: dict[str, int] = {}
    for entry in services:
        service_id = entry[0]
        public = catalog.public_service_price(service_id, category)
        discounted = catalog.service_price(service_id, category, promo_code=code)
        if public is None or discounted is None:
            continue
        if discounted < public:
            prices[service_id] = discounted
    return prices


@router.post("/promos/validate", response_model=PromoValidateResponse)
async def validate_promo(body: PromoValidateRequest) -> PromoValidateResponse:
    """Validate a promo code and surface its discounted prices for the
    customer's vehicle category.

    Always returns ``200`` — invalid / inactive codes get ``valid=false``
    rather than ``404``. A ``404`` here would let an attacker enumerate
    valid codes by probing the absence-of-404 channel.
    """
    code = catalog.normalize_promo_code(body.code)
    if not code:
        logger.info(
            "promos.validate code=- category=%s valid=False discounts_count=0",
            body.category,
        )
        return PromoValidateResponse(valid=False)

    label = catalog.promo_label(code)
    if not label:
        # The code looks well-formed but is unknown / inactive at the catalog
        # layer. Same 200/false response — no enumeration hint.
        logger.info(
            "promos.validate code=%s category=%s valid=False discounts_count=0",
            code,
            body.category,
        )
        return PromoValidateResponse(valid=False)

    discounts = _build_promo_discount_map(code, body.category)
    logger.info(
        "promos.validate code=%s category=%s valid=True discounts_count=%d",
        code,
        body.category,
        len(discounts),
    )
    return PromoValidateResponse(valid=True, label=label, discounted_prices=discounts)


@router.get("/catalog/closed-dates", response_model=list[str])
async def list_catalog_closed_dates() -> list[str]:
    """ISO-date strings the shop is closed (Eids, etc.), sorted ascending.

    The PWA calendar uses this to grey out the corresponding days. Static
    catalog entries and DB-persisted closures are merged by
    :func:`catalog.active_closed_dates`.
    """
    closed = sorted(catalog.active_closed_dates())
    logger.info(
        "catalog.closed_dates listed count=%d first=%s last=%s",
        len(closed),
        closed[0] if closed else "-",
        closed[-1] if closed else "-",
    )
    return closed


__all__ = [
    "_DOMAIN_EXC_MAP",
    "_slots_with_lead_filter",
    "api_exception_handler",
    "domain_error_response",
    "get_services",
    "install_exception_handlers",
    "list_catalog_categories",
    "list_catalog_centers",
    "list_catalog_closed_dates",
    "list_catalog_time_slots",
    "router",
    "validate_promo",
]
