"""Pydantic schemas for the /api/v1/* router.

Every request model inherits from `StrictBase`, which sets:
- `extra="forbid"` so PWA typos (e.g. ``addons`` vs ``addon_ids``) surface as 422
  at the contract boundary instead of being silently dropped.
- `str_strip_whitespace=True` so leading/trailing whitespace is stripped on every
  string field before further validation (belt-and-suspenders for `clean_text`).

Response models inherit from plain `BaseModel` — the server is trusted to
populate exactly the fields documented in the OpenAPI schema.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Strict base for all request models ────────────────────────────────────


class StrictBase(BaseModel):
    """Every request model rejects unknown fields (``extra='forbid'``) so PWA
    typos surface as 422 instead of being silently dropped."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ── Booking creation ──────────────────────────────────────────────────────


class VehicleInfo(StrictBase):
    make: Optional[str] = Field(None, max_length=64)
    color: Optional[str] = Field(None, max_length=64)
    plate: Optional[str] = Field(None, max_length=64)


class LocationInfo(StrictBase):
    kind: Literal["home", "center"]
    pin_address: Optional[str] = Field(None, max_length=200)
    address_details: Optional[str] = Field(None, max_length=200)
    center_id: Optional[str] = Field(None, max_length=64)


class BookingCreateRequest(StrictBase):
    phone: str = Field(..., min_length=8, max_length=32)
    name: str = Field(..., min_length=1, max_length=120)
    category: Literal["A", "B", "C", "MOTO"]
    vehicle: Optional[VehicleInfo] = None
    location: LocationInfo
    promo_code: Optional[str] = Field(None, max_length=40)
    service_id: str = Field(..., min_length=1, max_length=64)
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    slot: str = Field(..., min_length=1, max_length=64)
    note: Optional[str] = Field(None, max_length=500)
    addon_ids: list[str] = Field(default_factory=list, max_length=10)
    client_request_id: Optional[str] = Field(
        None, max_length=64, pattern=r"^[a-zA-Z0-9-]{8,64}$"
    )
    bookings_token: Optional[str] = Field(None, max_length=128)

    @field_validator("category", mode="before")
    @classmethod
    def _category_uppercase(cls, v: object) -> object:
        # `mode="before"` runs prior to the Literal check so "a" → "A" is
        # accepted silently. Non-string inputs pass through unchanged and the
        # standard Literal validator will reject them.
        if isinstance(v, str):
            return v.upper()
        return v

    @field_validator("date")
    @classmethod
    def _date_must_parse(cls, v: str) -> str:
        # Pattern already enforced YYYY-MM-DD shape; this catches impossible
        # calendar dates like "2026-02-30".
        _date.fromisoformat(v)
        return v


class BookingLineItemOut(BaseModel):
    kind: Literal["main", "addon"]
    service_id: str
    label: str
    price_dh: int
    regular_price_dh: Optional[int] = None
    sort_order: int


class BookingCreateResponse(BaseModel):
    ref: str
    status: str
    price_dh: int
    total_dh: int
    vehicle_label: str
    service_label: str
    date_label: str
    slot_label: str
    location_label: str
    line_items: list[BookingLineItemOut]
    bookings_token: str
    # True when this response was replayed from a prior request — lets the PWA
    # show a subtle "Réservation déjà enregistrée" hint.
    is_idempotent_replay: bool = False


# ── Promo validate ────────────────────────────────────────────────────────


class PromoValidateRequest(StrictBase):
    code: str = Field(..., min_length=1, max_length=40)
    category: Literal["A", "B", "C", "MOTO"]

    @field_validator("category", mode="before")
    @classmethod
    def _category_uppercase(cls, v: object) -> object:
        if isinstance(v, str):
            return v.upper()
        return v


class PromoValidateResponse(BaseModel):
    valid: bool
    label: Optional[str] = None
    discounted_prices: dict[str, int] = Field(default_factory=dict)


# ── Bootstrap (single round-trip for the PWA shell) ───────────────────────


class ServiceOut(BaseModel):
    id: str
    name: str
    desc: str
    price_dh: int
    # Populated only when a promo discount applies — lets the PWA strike-through.
    regular_price_dh: Optional[int] = None
    bucket: Literal["wash", "detailing", "moto"]


class CategoryOut(BaseModel):
    id: str
    label: str
    sub: str
    kind: Literal["car", "moto"]


class CenterOut(BaseModel):
    id: str
    name: str
    details: str


class TimeSlotOut(BaseModel):
    id: str
    label: str
    period: str


class BootstrapResponse(BaseModel):
    categories: list[CategoryOut]
    services: dict[str, list[ServiceOut]]  # keys: 'wash'+'detailing' (cars) OR 'moto'
    centers: list[CenterOut]
    time_slots: list[TimeSlotOut]
    closed_dates: list[str]
    # Echoes the ETag seed so PWA logs include the catalog revision.
    catalog_version: str


# ── Bookings list ─────────────────────────────────────────────────────────


class BookingListItemOut(BaseModel):
    ref: str
    status: str
    status_label: str  # French label for back-compat; PWA should localize status.
    service_label: str
    service_id: str
    vehicle_label: str
    date_iso: str
    date_label: str
    slot_id: str
    slot_label: str
    slot_start_hour: int
    slot_end_hour: int
    location_label: str
    total_price_dh: int
    created_at: str  # ISO 8601


class BookingsListResponse(BaseModel):
    bookings: list[BookingListItemOut]
    next_cursor: Optional[str] = None


# ── Errors ────────────────────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    field: Optional[str] = None  # request body field that triggered the error
    details: dict = Field(default_factory=dict)


__all__ = [
    "StrictBase",
    "VehicleInfo",
    "LocationInfo",
    "BookingCreateRequest",
    "BookingLineItemOut",
    "BookingCreateResponse",
    "PromoValidateRequest",
    "PromoValidateResponse",
    "ServiceOut",
    "CategoryOut",
    "CenterOut",
    "TimeSlotOut",
    "BootstrapResponse",
    "BookingListItemOut",
    "BookingsListResponse",
    "ErrorResponse",
]
