"""Booking record + reference generator."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from . import catalog
from .api_validation import clean_text

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .api_schemas import BookingCreateRequest

# In-memory booking counter. For MVP only — resets on Railway redeploy.
# TODO: move to persistent store (SQLite/Postgres) in v0.3.
_counter = 0
_bookings: list[dict] = []


@dataclass
class Booking:
    phone: str
    name: str = ""
    vehicle_type: str = ""      # label, e.g. "A — Citadine" or "🏍️ Moto / Scooter"
    category: str = ""          # pricing key: "A" / "B" / "C" / "MOTO"
    car_model: str = ""         # free text, e.g. "Dacia Logan"
    color: str = ""             # label, e.g. "Blanc"
    service: str = ""           # svc_ext / svc_cpl / svc_sal / svc_pol / svc_scooter / svc_moto
    service_bucket: str = ""    # "wash" or "detailing" (cars only) — which menu the customer came from
    service_label: str = ""     # "Le Complet — 125 DH" (what customer saw)
    price_dh: int = 0           # resolved price in DH at the time of booking
    location_mode: str = ""     # "home" or "center"
    center_id: str = ""         # ctr_casa / ... stable center key
    center: str = ""            # ctr_casa / ...
    geo: str = ""               # WhatsApp location pin (home only) — "name | address | 📍 lat, lng"
    location_name: str = ""     # WhatsApp location name, if provided
    location_address: str = ""  # WhatsApp location address, if provided
    latitude: float | None = None
    longitude: float | None = None
    address: str = ""           # free-text address + access notes (home only)
    date_label: str = ""        # "Aujourd'hui" / "Demain" / "2026-04-19"
    date_iso: str = ""          # YYYY-MM-DD stable appointment date
    slot_id: str = ""           # slot_9_11 / ...
    slot: str = ""              # slot_9_11 / ...
    note: str = ""              # optional customer note
    ref: str = ""               # assigned at confirmation
    created_at: str = ""        # ISO timestamp when confirmed
    addon_service: str = ""        # svc_pol / svc_cer6m / … if customer accepted the -10% Esthétique upsell
    addon_service_label: str = ""  # "Le Polissage — 891 DH (-10%)"
    addon_price_dh: int = 0        # discounted DH price of the addon

    # Promo code (partner preferential tariff, e.g. YS26). Empty string
    # means the public / regular grid applies. Captured BEFORE the service
    # menu so the list rows render the correct (discounted) prices.
    promo_code: str = ""            # UPPERCASE canonical code, e.g. "YS26"
    promo_label: str = ""           # Human-readable, e.g. "Yasmine Signature"
    price_regular_dh: int = 0       # Public price at time of booking (for savings math)
    client_request_id: str | None = None  # PWA idempotency key, when supplied

    # Transient state for the paginated date picker (BOOK_WHEN). Not persisted
    # into `_bookings` in any meaningful way — just survives the round-trip
    # between "Voir plus" taps.
    when_page: int = 0
    when_dates: list[str] = field(default_factory=list)  # ISO dates currently offered

    def assign_ref(
        self,
        *,
        counter_floor: int = 0,
        counter_value: int | None = None,
        record_shadow: bool = True,
    ) -> str:
        global _counter
        if counter_value is None:
            if counter_floor > _counter:
                _counter = counter_floor
            _counter += 1
            counter = _counter
        else:
            counter = counter_value
            if counter > _counter:
                _counter = counter
        year = datetime.now(timezone.utc).year
        self.ref = f"EW-{year}-{counter:04d}"
        self.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if record_shadow:
            _bookings.append(asdict(self))
        log.info(
            "booking confirmed ref=%s phone_hash=%s",
            self.ref,
            hashlib.sha256(self.phone.encode("utf-8")).hexdigest()[:12] if self.phone else "-",
        )
        return self.ref


def from_api_payload(
    payload: "BookingCreateRequest",
    *,
    server_price_dh: int,
    server_regular_price_dh: int,
    service_label: str,
    vehicle_label: str,
    location_label: str,
    date_label: str,
    slot_label: str,
    promo_label: str | None = None,
) -> Booking:
    """Pure conversion: validated API payload plus server labels/prices to Booking."""
    from .notifications import normalize_phone

    normalized_phone = normalize_phone(payload.phone)
    promo_code = catalog.normalize_promo_code(payload.promo_code) if payload.promo_code else ""
    # NB: every str field below defaults to ``""`` (not None) — the Booking
    # dataclass declares them as ``str = ""`` and the matching BookingRow
    # columns are nullable=False. Passing None worked on SQLite (which is
    # permissive) but blew up Postgres with a NOT NULL violation on the
    # first omitted-vehicle / home-without-pin-address PWA booking
    # (ewash-len). ``client_request_id``, ``latitude`` and ``longitude``
    # stay None because their model columns *are* nullable.
    booking = Booking(
        phone=normalized_phone,
        name=clean_text(payload.name, max_len=120) or "",
        category=payload.category,
        vehicle_type=vehicle_label,
        car_model=(clean_text(payload.vehicle.make, max_len=64) or "") if payload.vehicle else "",
        color=(clean_text(payload.vehicle.color, max_len=64) or "") if payload.vehicle else "",
        location_mode=payload.location.kind,
        center_id=payload.location.center_id or "",
        center=location_label if payload.location.kind == "center" else "",
        location_name="",
        location_address=(payload.location.pin_address or "") if payload.location.kind == "home" else "",
        address=clean_text(payload.location.address_details, max_len=200) or "",
        latitude=None,
        longitude=None,
        geo="",
        promo_code=promo_code,
        promo_label=promo_label or "",
        service=payload.service_id,
        service_bucket=_bucket_for(payload.service_id),
        service_label=service_label,
        price_dh=server_price_dh,
        price_regular_dh=server_regular_price_dh,
        date_iso=payload.date,
        date_label=date_label,
        slot_id=payload.slot,
        slot=slot_label,
        note=clean_text(payload.note, max_len=500) or "",
        addon_service="",
        addon_service_label="",
        addon_price_dh=0,
        client_request_id=payload.client_request_id,
        when_page=0,
        when_dates=[],
    )
    log.debug(
        "ewash.booking.from_api phone_hash=%s category=%s service=%s price=%d "
        "promo=%s has_vehicle=%s addons=%d",
        _hash_for_log(normalized_phone),
        booking.category,
        booking.service,
        booking.price_dh,
        booking.promo_code or "-",
        "true" if payload.vehicle else "false",
        len(payload.addon_ids),
    )
    return booking


def _bucket_for(service_id: str) -> str:
    """Lookup the service's bucket (wash | detailing | moto)."""
    for catalog_service_id, *_ in catalog.SERVICES_WASH:
        if catalog_service_id == service_id:
            return "wash"
    for catalog_service_id, *_ in catalog.SERVICES_DETAILING:
        if catalog_service_id == service_id:
            return "detailing"
    for catalog_service_id, *_ in catalog.SERVICES_MOTO:
        if catalog_service_id == service_id:
            return "moto"
    raise ValueError(f"Unknown service_id={service_id}")


def _hash_for_log(value: str, *, length: int = 6) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length] if value else "-"


def all_bookings() -> list[dict]:
    """For /bookings debug endpoint."""
    return list(_bookings)


def update_booking(ref: str, **fields) -> None:
    """Patch an already-persisted booking in place — used when the customer
    accepts a post-confirmation upsell (e.g. the -10% Esthétique add-on)."""
    for b in _bookings:
        if b.get("ref") == ref:
            b.update(fields)
            log.info("booking updated ref=%s fields=%s", ref, fields)
            return
    log.warning("update_booking: ref=%s not found", ref)
