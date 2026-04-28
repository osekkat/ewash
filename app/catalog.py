"""Static catalog for Ewash — matches the Apr 2026 printed tariff sheet.

Pricing categories A/B/C are the industry-standard size tiers Ewash prints
on their own flyer. Moto is a separate lane with its own 2-option service list.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import re

from sqlalchemy import Engine, delete, select

from .config import settings
from .db import init_db, make_engine, session_scope
from .models import PromoCodeRow, PromoDiscountRow, ServicePriceRow

log = logging.getLogger(__name__)

# ── Vehicle categories ─────────────────────────────────────────────────────
# Shown as a WhatsApp LIST (4 rows). Row format: (id, title ≤24 chars, desc).
# The first char of `title` ("A", "B", "C") is used as the category key.
VEHICLE_CATEGORIES = [
    ("veh_a",    "A — Citadine",          "Clio, Sandero, i10, Picanto…"),
    ("veh_b",    "B — Berline / SUV",     "Megane, Duster, Tucson, Kadjar…"),
    ("veh_c",    "C — Grande berline/SUV","X5, Tiguan, Touareg, Q7…"),
    ("veh_moto", "🏍️ Moto / Scooter",     "Deux roues — tarif unique"),
]

# Map vehicle row id → single-letter pricing category. Moto is handled separately.
VEHICLE_CATEGORY_KEY = {
    "veh_a":    "A",
    "veh_b":    "B",
    "veh_c":    "C",
    "veh_moto": "MOTO",
}


# ── Services for cars (A/B/C) ──────────────────────────────────────────────
# Split into 2 buckets, matching the Ewash flyer layout:
#   (1) LAVAGES — core wash formulas (maintenance / weekly recurring)
#   (2) ESTHÉTIQUE — premium detailing (polish, ceramic, renovation, lustre)
# Row format: (id, short_name, description ≤72 chars, prices_dict{A,B,C}).

SERVICES_WASH = [
    ("svc_ext",  "L'Extérieur",  "Carrosserie, vitres, jantes + wax 1 semaine",
        {"A": 60,  "B": 65,   "C": 70}),
    ("svc_cpl",  "Le Complet",   "L'Extérieur + intérieur + aspirateur tapis/sièges",
        {"A": 115, "B": 125,  "C": 135}),
    ("svc_sal",  "Le Salon",     "Le Complet + injection/extraction sièges & tissus",
        {"A": 490, "B": 540,  "C": 590}),
]

SERVICES_DETAILING = [
    ("svc_pol",      "Le Polissage",        "Rénov. carrosserie + protection hydrophobe 4 sem.",
        {"A": 990, "B": 1070, "C": 1150}),
    ("svc_cer6m",    "Céramique 6m",        "Protection céramique longue durée (6 mois)",
        {"A": 800, "B": 800,  "C": 800}),
    ("svc_cer6w",    "Céramique 6s",        "Protection céramique express (6 semaines)",
        {"A": 200, "B": 200,  "C": 200}),
    ("svc_cuir",     "Rénov. Cuir",         "Nettoyage & nourrissage des sièges et garnitures cuir",
        {"A": 250, "B": 250,  "C": 250}),
    ("svc_plastq",   "Rénov. Plast.",       "Rénovation & protection plastiques (6 mois)",
        {"A": 150, "B": 150,  "C": 250}),
    ("svc_optq",     "Rénov. Optiques",     "Ponçage + polissage des optiques de phares",
        {"A": 150, "B": 150,  "C": 150}),
    ("svc_lustre",   "Lustrage",            "Lustrage carrosserie (sans polissage)",
        {"A": 600, "B": 600,  "C": 700}),
]

# Backward-compat: flat list used by price/name lookups that scan everything.
SERVICES_CAR = SERVICES_WASH + SERVICES_DETAILING

# ── Services for moto/scooter ──────────────────────────────────────────────
# Single flat price, no category. Row: (id, label, description, price).
SERVICES_MOTO = [
    ("svc_scooter", "Scooter",  "Lavage complet scooter 2 roues", 85),
    ("svc_moto",    "Moto",     "Lavage complet moto",           105),
]


# ── Colors ─────────────────────────────────────────────────────────────────
# Free text only — we accept any color the user types. No buttons.
# (Leaving this list empty so legacy payload-matching paths never fire.)
COLORS: list[tuple[str, str]] = []


# ── Promo codes ────────────────────────────────────────────────────────────
# Per-partner preferential tariffs. When a customer enters a valid code during
# booking, service_price() + build_car_service_rows() use the discounted grid
# instead of the public one. Moto is intentionally excluded — the printed
# flyers show no moto discount on any partner tier.
#
# Add new codes by dropping a new entry keyed on the UPPERCASE code. Keep keys
# alphanumeric (partner DMs + printed flyers tend to be fat-fingered).
PROMO_CODES: dict[str, dict] = {
    "YS26": {
        "label": "Yasmine Signature",
        # Regular → promo price map per service_id × category.
        # Matches "Tarifs Exclusifs Yasmine Signature" Apr-2026 flyer.
        "discounts": {
            "svc_ext":    {"A": 55,  "B": 60,  "C": 65},
            "svc_cpl":    {"A": 100, "B": 110, "C": 120},
            "svc_sal":    {"A": 415, "B": 460, "C": 500},
            "svc_pol":    {"A": 790, "B": 856, "C": 920},
            "svc_cer6m":  {"A": 640, "B": 640, "C": 640},
            "svc_cer6w":  {"A": 160, "B": 160, "C": 160},
            "svc_cuir":   {"A": 200, "B": 200, "C": 200},
            "svc_plastq": {"A": 120, "B": 120, "C": 200},
            "svc_optq":   {"A": 200, "B": 200, "C": 200},
            "svc_lustre": {"A": 480, "B": 480, "C": 560},
            # MOTO intentionally excluded (no partner discount on 2-wheels).
        },
    },
}


CAR_PRICE_CATEGORIES = ("A", "B", "C")
MOTO_PRICE_CATEGORY = "MOTO"


@dataclass(frozen=True)
class PromoCodeView:
    code: str
    label: str
    active: bool
    discounts: dict[tuple[str, str], int]


@lru_cache(maxsize=1)
def _catalog_engine() -> Engine | None:
    if not settings.database_url:
        return None
    engine = make_engine(settings.database_url)
    init_db(engine)
    return engine


def catalog_cache_clear() -> None:
    """Clear cached DB state after admin catalog writes or test setting changes."""
    _catalog_engine.cache_clear()


def _engine_or_configured(engine: Engine | None = None) -> Engine | None:
    return engine if engine is not None else _catalog_engine()


def _clean_promo_code(text: str) -> str:
    return text.strip().strip("'\"“”‘’ ").upper()


def _default_public_price(service_id: str, category: str) -> int | None:
    if category == MOTO_PRICE_CATEGORY:
        for sid, _name, _desc, price in SERVICES_MOTO:
            if sid == service_id:
                return price
        return None
    for sid, _name, _desc, prices in SERVICES_CAR:
        if sid == service_id:
            return prices.get(category)
    return None


def public_service_price(service_id: str, category: str, *, engine: Engine | None = None) -> int | None:
    db_engine = _engine_or_configured(engine)
    if db_engine is not None:
        try:
            with session_scope(db_engine) as session:
                row = session.scalars(
                    select(ServicePriceRow).where(
                        ServicePriceRow.service_id == service_id,
                        ServicePriceRow.category == category,
                    )
                ).first()
                if row is not None:
                    return row.price_dh
        except Exception:
            log.exception("public_service_price failed; falling back to static catalog")
    return _default_public_price(service_id, category)


def upsert_public_prices(updates: dict[tuple[str, str], int], *, engine: Engine | None = None) -> int:
    db_engine = _engine_or_configured(engine)
    if db_engine is None:
        raise RuntimeError("DATABASE_URL is not configured")
    count = 0
    with session_scope(db_engine) as session:
        for (service_id, category), price_dh in updates.items():
            row = session.scalars(
                select(ServicePriceRow).where(
                    ServicePriceRow.service_id == service_id,
                    ServicePriceRow.category == category,
                )
            ).first()
            if row is None:
                session.add(ServicePriceRow(service_id=service_id, category=category, price_dh=price_dh))
            else:
                row.price_dh = price_dh
            count += 1
    catalog_cache_clear()
    return count


def _db_promo_view(code: str, *, engine: Engine | None = None) -> PromoCodeView | None:
    db_engine = _engine_or_configured(engine)
    if db_engine is None:
        return None
    try:
        with session_scope(db_engine) as session:
            row = session.get(PromoCodeRow, code)
            if row is None:
                return None
            discounts = {
                (discount.service_id, discount.category): discount.price_dh
                for discount in session.scalars(
                    select(PromoDiscountRow).where(PromoDiscountRow.promo_code == code)
                ).all()
            }
            return PromoCodeView(code=row.code, label=row.label, active=row.active, discounts=discounts)
    except Exception:
        log.exception("_db_promo_view failed; falling back to static promo catalog")
        return None


def _static_promo_view(code: str) -> PromoCodeView | None:
    promo = PROMO_CODES.get(code)
    if promo is None:
        return None
    discounts: dict[tuple[str, str], int] = {}
    for service_id, prices in promo.get("discounts", {}).items():
        for category, price_dh in prices.items():
            discounts[(service_id, category)] = price_dh
    return PromoCodeView(code=code, label=str(promo.get("label") or code), active=True, discounts=discounts)


def list_promo_codes(*, engine: Engine | None = None) -> tuple[PromoCodeView, ...]:
    promos = {code: view for code in PROMO_CODES if (view := _static_promo_view(code)) is not None}
    db_engine = _engine_or_configured(engine)
    if db_engine is not None:
        try:
            with session_scope(db_engine) as session:
                rows = session.scalars(select(PromoCodeRow).order_by(PromoCodeRow.code)).all()
                for row in rows:
                    discounts = {
                        (discount.service_id, discount.category): discount.price_dh
                        for discount in session.scalars(
                            select(PromoDiscountRow).where(PromoDiscountRow.promo_code == row.code)
                        ).all()
                    }
                    promos[row.code] = PromoCodeView(
                        code=row.code,
                        label=row.label,
                        active=row.active,
                        discounts=discounts,
                    )
        except Exception:
            log.exception("list_promo_codes failed; falling back to static promo catalog")
    return tuple(promos[code] for code in sorted(promos))


def upsert_promo_code(
    *,
    code: str,
    label: str,
    active: bool,
    discounts: dict[tuple[str, str], int],
    engine: Engine | None = None,
) -> str:
    normalized = _clean_promo_code(code)
    if not normalized or not re.fullmatch(r"[A-Z0-9_-]{2,40}", normalized):
        raise ValueError("Promo code must be 2-40 letters, numbers, underscores, or hyphens")
    db_engine = _engine_or_configured(engine)
    if db_engine is None:
        raise RuntimeError("DATABASE_URL is not configured")
    with session_scope(db_engine) as session:
        row = session.get(PromoCodeRow, normalized)
        if row is None:
            row = PromoCodeRow(code=normalized, label=label.strip() or normalized, active=active)
            session.add(row)
        else:
            row.label = label.strip() or normalized
            row.active = active
        session.execute(delete(PromoDiscountRow).where(PromoDiscountRow.promo_code == normalized))
        for (service_id, category), price_dh in discounts.items():
            session.add(
                PromoDiscountRow(
                    promo_code=normalized,
                    service_id=service_id,
                    category=category,
                    price_dh=price_dh,
                )
            )
    catalog_cache_clear()
    return normalized


def normalize_promo_code(text: str) -> str | None:
    """Normalize free-text promo input. Returns the canonical UPPERCASE code
    if valid, else None. Case-insensitive, trims whitespace and stray quotes."""
    if not text:
        return None
    cleaned = _clean_promo_code(text)
    if not re.fullmatch(r"[A-Z0-9_-]{2,40}", cleaned):
        return None
    db_view = _db_promo_view(cleaned)
    if db_view is not None:
        return cleaned if db_view.active else None
    if cleaned in PROMO_CODES:
        return cleaned
    return None


def promo_label(code: str | None) -> str:
    """Human-readable partner label for a normalized code, or ''."""
    cleaned = _clean_promo_code(code or "")
    if not cleaned:
        return ""
    db_view = _db_promo_view(cleaned)
    if db_view is not None:
        return db_view.label if db_view.active else ""
    static_view = _static_promo_view(cleaned)
    return static_view.label if static_view else ""



# ── Closed days (Eids, etc.) ───────────────────────────────────────────────
# ISO dates (YYYY-MM-DD) the shop is closed — skipped when proposing dates.
# Update yearly: Eid dates shift ~10-11 days earlier each year.
CLOSED_DATES: set[str] = {
    "2026-05-27",  # Eid al-Adha 2026 day 1 — CONFIRM closer to the date
    "2026-05-28",  # Eid al-Adha 2026 day 2 — CONFIRM closer to the date
}


# ── Centers ────────────────────────────────────────────────────────────────
# TODO(omar): confirm exact addresses if more centers open later.
CENTERS = [
    ("ctr_casa", "Stand physique", "Mall Triangle Vert, Bouskoura · 7j/7 · 09h-22h30"),
]


# ── Time slots ─────────────────────────────────────────────────────────────
# Lavage jusqu'à 22h (dernier créneau 20h–22h).
SLOTS = [
    ("slot_9_11",   "09h – 11h",  "Matin"),
    ("slot_11_13",  "11h – 13h",  "Fin de matinée"),
    ("slot_14_16",  "14h – 16h",  "Début après-midi"),
    ("slot_16_18",  "16h – 18h",  "Fin d'après-midi"),
    ("slot_18_20",  "18h – 20h",  "Début de soirée"),
    ("slot_20_22",  "20h – 22h",  "Soirée"),
]


# ── Helpers ────────────────────────────────────────────────────────────────
def label_for(pairs, rid: str) -> str:
    """Return the human-readable label (index 1) for a given id."""
    for row in pairs:
        if row[0] == rid:
            return row[1]
    return rid


def build_car_service_rows(
    category: str,
    bucket: str = "all",
    promo_code: str | None = None,
) -> list[tuple[str, str, str]]:
    """Render car services as WhatsApp list rows (id, title, description).

    Title embeds the price for the customer's category inline, e.g.:
      "Le Complet — 125 DH"
    Description is the short feature list from the flyer.

    `bucket` selects which services to show:
      - "wash"       → SERVICES_WASH (L'Extérieur / Le Complet / Le Salon)
      - "detailing"  → SERVICES_DETAILING (Polissage / Céramique / Rénovations / Lustrage)
      - "all"        → both (legacy behaviour, kept for safety)

    `promo_code` (optional, UPPERCASE) swaps in the partner-preferential price
    where a discount row exists. Services not covered by the partner grid keep
    their regular price. Invalid codes are treated as no-promo.

    WhatsApp limits:
      - title ≤ 24 chars (we stay under)
      - description ≤ 72 chars
      - max 10 rows per section → detailing has 7, still well under cap
    """
    if bucket == "wash":
        source = SERVICES_WASH
    elif bucket == "detailing":
        source = SERVICES_DETAILING
    else:
        source = SERVICES_CAR

    rows = []
    normalized_promo = normalize_promo_code(promo_code or "") if promo_code else None
    for sid, name, desc, _prices in source:
        price = service_price(sid, category, promo_code=normalized_promo)
        title = f"{name} — {price} DH" if price is not None else name
        rows.append((sid, title[:24], desc[:72]))
    return rows


def build_moto_service_rows() -> list[tuple[str, str, str]]:
    """Render SERVICES_MOTO as WhatsApp list rows with inline prices."""
    rows = []
    for sid, name, desc, _price in SERVICES_MOTO:
        price = public_service_price(sid, MOTO_PRICE_CATEGORY)
        rows.append((sid, f"{name} — {price} DH"[:24], desc[:72]))
    return rows


def service_price(
    service_id: str,
    category: str,
    promo_code: str | None = None,
) -> int | None:
    """Look up the price for a given service+category. Returns DH integer or None.

    When `promo_code` is a valid UPPERCASE partner code, the partner grid wins
    for any service covered by that partner. Moto is never discounted.
    """
    if category == MOTO_PRICE_CATEGORY:
        return public_service_price(service_id, category)
    normalized_promo = normalize_promo_code(promo_code or "") if promo_code else None
    if normalized_promo:
        db_view = _db_promo_view(normalized_promo)
        promo_view = db_view if db_view is not None else _static_promo_view(normalized_promo)
        if promo_view is not None and promo_view.active:
            promo_price = promo_view.discounts.get((service_id, category))
            if promo_price is not None:
                return promo_price
    return public_service_price(service_id, category)


def service_name(service_id: str) -> str:
    """Short service name (without price), e.g. 'Le Complet'."""
    for sid, name, *_ in SERVICES_CAR:
        if sid == service_id:
            return name
    for sid, name, *_ in SERVICES_MOTO:
        if sid == service_id:
            return name
    return service_id
