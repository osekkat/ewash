"""Booking record + reference generator."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

log = logging.getLogger(__name__)

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
    center: str = ""            # ctr_casa / ...
    address: str = ""           # free text when location_mode == "home"
    date_label: str = ""        # "Aujourd'hui" / "Demain" / "2026-04-19"
    slot: str = ""              # slot_9_11 / ...
    note: str = ""              # optional customer note
    ref: str = ""               # assigned at confirmation
    created_at: str = ""        # ISO timestamp when confirmed

    def assign_ref(self) -> str:
        global _counter
        _counter += 1
        year = datetime.now(timezone.utc).year
        self.ref = f"EW-{year}-{_counter:04d}"
        self.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _bookings.append(asdict(self))
        log.info("booking confirmed ref=%s phone=%s payload=%s",
                 self.ref, self.phone, asdict(self))
        return self.ref


def all_bookings() -> list[dict]:
    """For /bookings debug endpoint."""
    return list(_bookings)
