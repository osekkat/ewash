"""In-memory conversation state keyed by phone number.

State machine:
  IDLE → MENU → (book path | services info | handoff)
  BOOK_NAME → BOOK_VEHICLE → BOOK_MODEL → BOOK_COLOR
  → BOOK_SERVICE_TYPE (🧼 Lavages | ✨ Esthétique)     ← car lane only
  → BOOK_SERVICE → BOOK_WHERE → (BOOK_ADDRESS | BOOK_CENTER)
  → BOOK_WHEN → BOOK_SLOT → BOOK_NOTE → (BOOK_NOTE_TEXT)?
  → BOOK_CONFIRM → DONE

Moto lane: goes straight from BOOK_VEHICLE to BOOK_SERVICE (single menu).

On any unexpected input we gracefully re-prompt the current step.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from .booking import Booking

log = logging.getLogger(__name__)

# TTL for stale conversations (seconds). After this, we reset to IDLE.
STATE_TTL = 60 * 60 * 2  # 2h


@dataclass
class Session:
    state: str = "IDLE"
    booking: Optional[Booking] = None
    last_seen: float = field(default_factory=time.time)


_sessions: dict[str, Session] = {}


def get(phone: str) -> Session:
    s = _sessions.get(phone)
    now = time.time()
    if s is None or (now - s.last_seen) > STATE_TTL:
        s = Session()
        _sessions[phone] = s
    s.last_seen = now
    return s


def reset(phone: str) -> None:
    _sessions[phone] = Session()


def start_booking(phone: str) -> Session:
    s = get(phone)
    s.state = "BOOK_NAME"
    s.booking = Booking(phone=phone)
    return s
