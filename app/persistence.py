"""Persistence service for confirmed WhatsApp bookings.

The WhatsApp flow still owns the deterministic customer experience. This module is
an adapter that mirrors confirmed in-memory Booking objects into the v0.3 CRM DB
so the admin dashboard can show real operational data.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
from typing import Iterable

from sqlalchemy import Engine, func, select, or_

from .booking import Booking, all_bookings
from .config import settings
from .db import init_db, make_engine, session_scope
from .models import (
    BookingReminderRow,
    BookingRow,
    BookingStatusEventRow,
    Customer,
    CustomerVehicle,
    VehicleColor,
    VehicleModel,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecentBooking:
    ref: str
    customer_name: str
    service_label: str
    status: str


@dataclass(frozen=True)
class AdminBookingListItem:
    ref: str
    customer_name: str
    customer_phone: str
    vehicle_label: str
    service_label: str
    addon_service_label: str
    status: str
    date_label: str
    slot: str
    location_label: str
    price_dh: int


@dataclass(frozen=True)
class AdminCustomerListItem:
    phone: str
    display_name: str
    booking_count: int
    vehicle_labels: tuple[str, ...]
    last_bot_stage: str = ""
    last_bot_stage_label: str = ""


@dataclass(frozen=True)
class DashboardSummary:
    total_bookings: int = 0
    confirmed_bookings: int = 0
    awaiting_confirmation: int = 0
    pending_ewash_confirmation: int = 0
    customers: int = 0
    pending_reminders: int = 0
    recent_bookings: tuple[RecentBooking, ...] = ()
    db_available: bool = False


@lru_cache(maxsize=1)
def _configured_engine() -> Engine | None:
    if not settings.database_url:
        return None
    engine = make_engine(settings.database_url)
    init_db(engine)
    return engine


def _engine_or_configured(engine: Engine | None = None) -> Engine | None:
    if engine is not None:
        return engine
    return _configured_engine()


def _now() -> datetime:
    return datetime.now(timezone.utc)


_BOT_STAGE_LABELS = {
    "IDLE": "Hors parcours",
    "MENU": "Menu principal affiché",
    "HANDOFF": "Message à l'équipe",
    "BOOK_NAME": "Saisie du nom",
    "BOOK_VEHICLE": "Choix du véhicule",
    "BOOK_MODEL": "Saisie du modèle",
    "BOOK_COLOR": "Saisie de la couleur",
    "BOOK_WHERE": "Choix du lieu",
    "BOOK_CENTER": "Choix du stand Ewash",
    "BOOK_GEO": "Partage de localisation",
    "BOOK_ADDRESS": "Saisie de l'adresse",
    "BOOK_PROMO_ASK": "Question code promo",
    "BOOK_PROMO_CODE": "Saisie code promo",
    "BOOK_SERVICE": "Liste des prix affichée",
    "BOOK_WHEN": "Choix de la date",
    "BOOK_SLOT": "Choix du créneau",
    "BOOK_NOTE": "Question note client",
    "BOOK_NOTE_TEXT": "Saisie note client",
    "BOOK_CONFIRM": "Récap envoyé — attente client",
    "UPSELL_DETAILING": "Offre esthétique affichée",
    "UPSELL_DETAILING_PICK": "Liste upsell affichée",
}


def bot_stage_label(stage: str) -> str:
    return _BOT_STAGE_LABELS.get(stage or "", stage or "—")


_REF_RE = re.compile(r"^EW-(\d{4})-(\d+)$")


def _max_ref_counter(refs: Iterable[str], *, year: int) -> int:
    max_counter = 0
    for ref in refs:
        match = _REF_RE.match(ref or "")
        if not match or int(match.group(1)) != year:
            continue
        max_counter = max(max_counter, int(match.group(2)))
    return max_counter


def assign_booking_ref(booking: Booking, *, engine: Engine | None = None) -> str:
    """Assign a booking reference that is monotonic against persisted refs.

    The in-memory Booking counter resets on each Railway redeploy, while
    Postgres keeps old refs. Before confirming a booking, seed the in-memory
    counter from the DB max so a fresh process does not reuse EW-YYYY-0001 and
    get ignored as an existing persisted row.
    """
    db_engine = _engine_or_configured(engine)
    if db_engine is None:
        return booking.assign_ref()

    year = _now().year
    try:
        with session_scope(db_engine) as session:
            refs = session.scalars(
                select(BookingRow.ref).where(BookingRow.ref.like(f"EW-{year}-%"))
            ).all()
            counter_floor = _max_ref_counter(refs, year=year)
    except Exception:
        log.exception("assign_booking_ref failed to read DB refs; falling back to process counter")
        counter_floor = 0
    return booking.assign_ref(counter_floor=counter_floor)


def _vehicle_label(booking: Booking) -> str:
    if booking.category == "MOTO":
        return booking.vehicle_type or "Moto"
    parts = [booking.car_model.strip(), booking.color.strip()]
    label = " — ".join(p for p in parts if p)
    return label or booking.vehicle_type or "Véhicule"


def _normalize_vehicle_value(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def _find_or_create_vehicle_model(session, *, category: str, model: str) -> VehicleModel | None:
    normalized = _normalize_vehicle_value(model)
    if not normalized:
        return None
    existing = session.scalars(
        select(VehicleModel).where(
            VehicleModel.category == category,
            VehicleModel.normalized_name == normalized,
        )
    ).first()
    if existing is not None:
        existing.last_seen_at = _now()
        return existing
    row = VehicleModel(category=category, name=model.strip(), normalized_name=normalized, active=True, last_seen_at=_now())
    session.add(row)
    session.flush()
    return row


def _find_or_create_vehicle_color(session, *, color: str) -> VehicleColor | None:
    normalized = _normalize_vehicle_value(color)
    if not normalized:
        return None
    existing = session.scalars(
        select(VehicleColor).where(VehicleColor.normalized_name == normalized)
    ).first()
    if existing is not None:
        existing.last_seen_at = _now()
        return existing
    row = VehicleColor(name=color.strip(), normalized_name=normalized, active=True, last_seen_at=_now())
    session.add(row)
    session.flush()
    return row


def _find_or_create_customer(session, booking: Booking) -> Customer:
    customer = session.get(Customer, booking.phone)
    if customer is None:
        customer = Customer(phone=booking.phone, display_name=booking.name or "")
        session.add(customer)
        session.flush()
    elif booking.name:
        customer.display_name = booking.name
    customer.last_seen_at = _now()
    customer.booking_count = (customer.booking_count or 0) + 1
    return customer


def persist_customer_bot_stage(
    phone: str,
    stage: str,
    *,
    display_name: str = "",
    engine: Engine | None = None,
) -> Customer | None:
    """Persist the latest WhatsApp funnel stage for a phone number.

    This intentionally creates a customer row before confirmation so abandoned
    leads still show where they dropped in the admin portal.
    """
    db_engine = _engine_or_configured(engine)
    if db_engine is None or not phone:
        return None

    label = bot_stage_label(stage)
    with session_scope(db_engine) as session:
        customer = session.get(Customer, phone)
        if customer is None:
            customer = Customer(phone=phone, display_name=display_name or "")
            session.add(customer)
            session.flush()
        elif display_name and not customer.display_name:
            customer.display_name = display_name
        customer.last_seen_at = _now()
        customer.last_bot_stage = stage or ""
        customer.last_bot_stage_label = label
        customer.last_bot_stage_at = _now()
        session.flush()
        session.expunge(customer)
        return customer


def _find_or_create_vehicle(session, booking: Booking) -> CustomerVehicle | None:
    if not booking.phone:
        return None
    model = "" if booking.category == "MOTO" else (booking.car_model or "").strip()
    color = "" if booking.category == "MOTO" else (booking.color or "").strip()
    category = booking.category or ""
    vehicle_model = _find_or_create_vehicle_model(session, category=category, model=model) if model else None
    vehicle_color = _find_or_create_vehicle_color(session, color=color) if color else None
    conditions = [
        CustomerVehicle.customer_phone == booking.phone,
        CustomerVehicle.category == category,
        CustomerVehicle.active.is_(True),
    ]
    if vehicle_model is not None:
        conditions.append(or_(CustomerVehicle.model_id == vehicle_model.id, CustomerVehicle.model == model))
    else:
        conditions.append(CustomerVehicle.model == model)
    if vehicle_color is not None:
        conditions.append(or_(CustomerVehicle.color_id == vehicle_color.id, CustomerVehicle.color == color))
    else:
        conditions.append(CustomerVehicle.color == color)
    existing = session.scalars(select(CustomerVehicle).where(*conditions)).first()
    if existing is not None:
        existing.model_id = existing.model_id or (vehicle_model.id if vehicle_model else None)
        existing.color_id = existing.color_id or (vehicle_color.id if vehicle_color else None)
        existing.label = existing.label or _vehicle_label(booking)
        existing.last_used_at = _now()
        return existing

    vehicle = CustomerVehicle(
        customer_phone=booking.phone,
        category=category,
        model_id=vehicle_model.id if vehicle_model else None,
        color_id=vehicle_color.id if vehicle_color else None,
        model=model,
        color=color,
        label=_vehicle_label(booking),
        active=True,
        last_used_at=_now(),
    )
    session.add(vehicle)
    session.flush()
    return vehicle


def persist_confirmed_booking(booking: Booking, *, engine: Engine | None = None) -> BookingRow | None:
    """Mirror a confirmed WhatsApp booking into the CRM database.

    Returns the persisted BookingRow when a DB is configured. If the app is run
    without DATABASE_URL (local demos/tests that do not pass an engine), this is
    a safe no-op so the WhatsApp flow keeps working.
    """
    db_engine = _engine_or_configured(engine)
    if db_engine is None:
        log.info("persist_confirmed_booking skipped: DATABASE_URL not configured ref=%s", booking.ref)
        return None

    if not booking.ref:
        booking.assign_ref()

    with session_scope(db_engine) as session:
        existing = session.scalars(select(BookingRow).where(BookingRow.ref == booking.ref)).first()
        if existing is not None:
            return existing

        customer = _find_or_create_customer(session, booking)
        vehicle = _find_or_create_vehicle(session, booking)
        row = BookingRow(
            ref=booking.ref,
            customer_phone=customer.phone,
            customer_vehicle_id=vehicle.id if vehicle else None,
            status="pending_ewash_confirmation",
            customer_name=booking.name,
            vehicle_type=booking.vehicle_type,
            car_model=booking.car_model,
            color=booking.color,
            service_id=booking.service,
            service_bucket=booking.service_bucket,
            service_label=booking.service_label,
            price_dh=booking.price_dh,
            price_regular_dh=booking.price_regular_dh,
            promo_code=booking.promo_code,
            promo_label=booking.promo_label,
            location_mode=booking.location_mode,
            center=booking.center,
            geo=booking.geo,
            address=booking.address,
            date_label=booking.date_label,
            slot=booking.slot,
            note=booking.note,
            addon_service=booking.addon_service,
            addon_service_label=booking.addon_service_label,
            addon_price_dh=booking.addon_price_dh,
            raw_booking_json=json.dumps(asdict(booking), ensure_ascii=False, default=str),
        )
        session.add(row)
        session.flush()
        session.add(
            BookingStatusEventRow(
                booking_id=row.id,
                from_status="awaiting_confirmation",
                to_status="pending_ewash_confirmation",
                actor="customer",
                note="Confirmation WhatsApp",
            )
        )
        session.flush()
        session.expunge(row)
        return row


def persist_booking_addon(
    ref: str,
    *,
    addon_service: str,
    addon_service_label: str,
    addon_price_dh: int,
    engine: Engine | None = None,
) -> None:
    db_engine = _engine_or_configured(engine)
    if db_engine is None or not ref:
        return
    with session_scope(db_engine) as session:
        row = session.scalars(select(BookingRow).where(BookingRow.ref == ref)).first()
        if row is None:
            log.warning("persist_booking_addon: ref=%s not found", ref)
            return
        row.addon_service = addon_service
        row.addon_service_label = addon_service_label
        row.addon_price_dh = addon_price_dh


def _booking_dict_to_admin_item(row: dict) -> AdminBookingListItem:
    vehicle_label = " — ".join(str(row.get(part, "")).strip() for part in ("car_model", "color") if str(row.get(part, "")).strip())
    if not vehicle_label:
        vehicle_label = str(row.get("vehicle_type") or "")
    location_mode = str(row.get("location_mode") or "")
    location_label = str(row.get("center") or "") if location_mode == "center" else str(row.get("address") or row.get("geo") or location_mode)
    total_price_dh = int(row.get("price_dh") or 0) + int(row.get("addon_price_dh") or 0)
    return AdminBookingListItem(
        ref=str(row.get("ref") or ""),
        customer_name=str(row.get("name") or row.get("phone") or ""),
        customer_phone=str(row.get("phone") or ""),
        vehicle_label=vehicle_label,
        service_label=str(row.get("service_label") or row.get("service") or ""),
        addon_service_label=str(row.get("addon_service_label") or ""),
        status="pending_ewash_confirmation" if row.get("ref") else "draft",
        date_label=str(row.get("date_label") or ""),
        slot=str(row.get("slot") or ""),
        location_label=location_label,
        price_dh=total_price_dh,
    )


def _memory_booking_items(limit: int = 100) -> tuple[AdminBookingListItem, ...]:
    return tuple(_booking_dict_to_admin_item(row) for row in reversed(all_bookings()[-limit:]))


def _memory_customer_items(limit: int = 100) -> tuple[AdminCustomerListItem, ...]:
    grouped: dict[str, dict] = {}
    for row in all_bookings():
        phone = str(row.get("phone") or "")
        if not phone:
            continue
        item = grouped.setdefault(
            phone,
            {"display_name": str(row.get("name") or phone), "booking_count": 0, "vehicle_labels": set()},
        )
        item["booking_count"] += 1
        vehicle_label = " — ".join(str(row.get(part, "")).strip() for part in ("car_model", "color") if str(row.get(part, "")).strip())
        if not vehicle_label:
            vehicle_label = str(row.get("vehicle_type") or "")
        if vehicle_label:
            item["vehicle_labels"].add(vehicle_label)
    return tuple(
        AdminCustomerListItem(
            phone=phone,
            display_name=data["display_name"],
            booking_count=data["booking_count"],
            vehicle_labels=tuple(sorted(data["vehicle_labels"])),
        )
        for phone, data in list(grouped.items())[:limit]
    )


def admin_booking_list(*, engine: Engine | None = None, limit: int = 100) -> tuple[AdminBookingListItem, ...]:
    memory_items = _memory_booking_items(limit)
    db_engine = _engine_or_configured(engine)
    if db_engine is None:
        return memory_items
    try:
        with session_scope(db_engine) as session:
            rows = session.scalars(
                select(BookingRow).order_by(BookingRow.created_at.desc()).limit(limit)
            ).all()
            items: list[AdminBookingListItem] = []
            for row in rows:
                vehicle_label = " — ".join(part for part in (row.car_model, row.color) if part) or row.vehicle_type
                location_label = row.center if row.location_mode == "center" else (row.address or row.geo or row.location_mode)
                total_price_dh = (row.price_dh or 0) + (row.addon_price_dh or 0)
                items.append(
                    AdminBookingListItem(
                        ref=row.ref,
                        customer_name=row.customer_name or row.customer_phone,
                        customer_phone=row.customer_phone,
                        vehicle_label=vehicle_label,
                        service_label=row.service_label or row.service_id,
                        addon_service_label=row.addon_service_label or "",
                        status=row.status,
                        date_label=row.date_label,
                        slot=row.slot,
                        location_label=location_label,
                        price_dh=total_price_dh,
                    )
                )
            db_refs = {item.ref for item in items if item.ref}
            items.extend(item for item in memory_items if item.ref not in db_refs)
            return tuple(items[:limit])
    except Exception:
        log.exception("admin_booking_list failed; falling back to live memory")
        return memory_items


def admin_customer_list(*, engine: Engine | None = None, limit: int = 100) -> tuple[AdminCustomerListItem, ...]:
    memory_items = _memory_customer_items(limit)
    db_engine = _engine_or_configured(engine)
    if db_engine is None:
        return memory_items
    try:
        with session_scope(db_engine) as session:
            customers = session.scalars(
                select(Customer).order_by(Customer.last_seen_at.desc()).limit(limit)
            ).all()
            items: list[AdminCustomerListItem] = []
            for customer in customers:
                vehicles = session.scalars(
                    select(CustomerVehicle).where(
                        CustomerVehicle.customer_phone == customer.phone,
                        CustomerVehicle.active.is_(True),
                    )
                ).all()
                labels = tuple(vehicle.label or " — ".join(part for part in (vehicle.model, vehicle.color) if part) for vehicle in vehicles)
                items.append(
                    AdminCustomerListItem(
                        phone=customer.phone,
                        display_name=customer.display_name or customer.phone,
                        booking_count=customer.booking_count or 0,
                        vehicle_labels=tuple(label for label in labels if label),
                        last_bot_stage=customer.last_bot_stage or "",
                        last_bot_stage_label=customer.last_bot_stage_label or bot_stage_label(customer.last_bot_stage or ""),
                    )
                )
            db_phones = {item.phone for item in items if item.phone}
            items.extend(item for item in memory_items if item.phone not in db_phones)
            return tuple(items[:limit])
    except Exception:
        log.exception("admin_customer_list failed; falling back to live memory")
        return memory_items


def admin_dashboard_summary(*, engine: Engine | None = None, recent_limit: int = 5) -> DashboardSummary:
    db_engine = _engine_or_configured(engine)
    if db_engine is None:
        return DashboardSummary()

    try:
        with session_scope(db_engine) as session:
            total = session.scalar(select(func.count()).select_from(BookingRow)) or 0
            confirmed = session.scalar(
                select(func.count()).select_from(BookingRow).where(BookingRow.status == "confirmed")
            ) or 0
            awaiting = session.scalar(
                select(func.count()).select_from(BookingRow).where(BookingRow.status == "awaiting_confirmation")
            ) or 0
            pending_ewash = session.scalar(
                select(func.count()).select_from(BookingRow).where(BookingRow.status == "pending_ewash_confirmation")
            ) or 0
            customers = session.scalar(select(func.count()).select_from(Customer)) or 0
            reminders = session.scalar(
                select(func.count()).select_from(BookingReminderRow).where(BookingReminderRow.status == "pending")
            ) or 0
            rows = session.scalars(
                select(BookingRow).order_by(BookingRow.created_at.desc()).limit(recent_limit)
            ).all()
            recent = tuple(
                RecentBooking(
                    ref=row.ref,
                    customer_name=row.customer_name or row.customer_phone,
                    service_label=row.service_label or row.service_id,
                    status=row.status,
                )
                for row in rows
            )
            return DashboardSummary(
                total_bookings=total,
                confirmed_bookings=confirmed,
                awaiting_confirmation=awaiting,
                pending_ewash_confirmation=pending_ewash,
                customers=customers,
                pending_reminders=reminders,
                recent_bookings=recent,
                db_available=True,
            )
    except Exception:
        log.exception("admin_dashboard_summary failed")
        return DashboardSummary()
