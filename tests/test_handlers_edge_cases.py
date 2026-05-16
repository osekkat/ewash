"""Adversarial edge-case coverage for the WhatsApp bot state machine."""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from app import booking as booking_store
from app import handlers, meta, state
from app.booking import Booking
from app.config import settings
from app.db import init_db, make_engine, session_scope
from app.models import (
    ALLOWED_STATUS_TRANSITIONS,
    BookingRow,
    BookingStatusEventRow,
)
from app.persistence import _configured_engine


DISPATCH_STATES = tuple(handlers._DISPATCH.keys())
TEXT_CORPUS = (
    ("empty", ""),
    ("emoji", "🙂"),
    ("long", "x" * 10_000),
    ("control_sql", "\x00\x1f'; DROP TABLE bookings; --"),
    ("jsonish", '{"payload_id": "confirm_yes", "state": "BOOK_CONFIRM"}'),
)


class OutboundRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send_text(self, to: str, body: str) -> dict:
        self.calls.append({"kind": "text", "to": to, "body": body})
        return {}

    async def send_buttons(self, to: str, body: str, buttons: list[tuple[str, str]]) -> dict:
        self.calls.append({"kind": "buttons", "to": to, "body": body, "buttons": buttons})
        return {}

    async def send_list(
        self,
        to: str,
        body: str,
        button_label: str,
        rows: list[tuple[str, str, str]],
        section_title: str = "Options",
    ) -> dict:
        self.calls.append(
            {
                "kind": "list",
                "to": to,
                "body": body,
                "button_label": button_label,
                "rows": rows,
                "section_title": section_title,
            }
        )
        return {}

    async def send_template(self, *args, **kwargs) -> dict:
        self.calls.append({"kind": "template", "args": args, "kwargs": kwargs})
        return {}

    async def send_image_link(self, to: str, image_url: str, caption: str | None = None) -> dict:
        self.calls.append(
            {
                "kind": "image",
                "to": to,
                "image_url": image_url,
                "caption": caption,
            }
        )
        return {}


def _text_message(phone: str, message_id: str, body: str) -> dict[str, Any]:
    return {"id": message_id, "from": phone, "type": "text", "text": {"body": body}}


def _interactive_message(
    phone: str,
    message_id: str,
    payload_id: str,
    *,
    kind: str = "button_reply",
) -> dict[str, Any]:
    return {
        "id": message_id,
        "from": phone,
        "type": "interactive",
        "interactive": {
            "type": kind,
            kind: {"id": payload_id, "title": payload_id},
        },
    }


def _malformed_interactive_message(phone: str, message_id: str, shape: str) -> dict[str, Any]:
    if shape == "missing_reply_object":
        interactive = {"type": "button_reply"}
    elif shape == "missing_id":
        interactive = {"type": "button_reply", "button_reply": {"title": "No id"}}
    elif shape == "empty_id":
        interactive = {"type": "list_reply", "list_reply": {"id": "", "title": ""}}
    elif shape == "unknown_interactive_type":
        interactive = {"type": "not_a_real_whatsapp_type", "not_a_real_whatsapp_type": {}}
    else:
        raise AssertionError(f"unknown malformed shape {shape}")
    return {"id": message_id, "from": phone, "type": "interactive", "interactive": interactive}


def _complete_booking(phone: str, *, appointment_date: date | None = None) -> Booking:
    appointment_date = appointment_date or (date.today() + timedelta(days=1))
    booking = Booking(phone=phone)
    booking.name = "Fuzz Client"
    booking.vehicle_type = "B - Berline / SUV"
    booking.category = "B"
    booking.car_model = "Dacia Logan"
    booking.color = "Blanc"
    booking.service = "svc_cpl"
    booking.service_bucket = "wash"
    booking.service_label = "Le Complet - 110 DH"
    booking.price_dh = 110
    booking.price_regular_dh = 125
    booking.location_mode = "home"
    booking.address = "Bouskoura, portail bleu"
    booking.geo = "33.5,-7.6"
    booking.date_iso = appointment_date.isoformat()
    booking.date_label = appointment_date.isoformat()
    booking.slot_id = "slot_9_11"
    booking.slot = "09h-11h"
    booking.note = "Appeler en arrivant"
    booking.ref = "EW-2026-9999"
    booking.when_page = 0
    booking.when_dates = [
        (date.today() + timedelta(days=offset)).isoformat()
        for offset in range(15)
    ]
    return booking


def _seed_session(
    phone: str,
    state_name: str,
    *,
    booking: Booking | None = None,
    expired: bool = False,
):
    state.reset(phone)
    sess = state.get(phone)
    sess.state = state_name
    sess.booking = booking or _complete_booking(phone)
    if expired:
        sess.last_seen = time.time() - state.STATE_TTL - 5
    return sess


def _booking_row_count(engine) -> int:
    with session_scope(engine) as session:
        return session.scalar(select(func.count()).select_from(BookingRow)) or 0


def _assert_no_invalid_status_events(engine) -> None:
    with session_scope(engine) as session:
        events = session.scalars(select(BookingStatusEventRow)).all()
        for event in events:
            allowed = ALLOWED_STATUS_TRANSITIONS.get(event.from_status, set())
            assert event.to_status in allowed, (
                f"invalid FSM transition {event.from_status} -> {event.to_status}"
            )


def _assert_no_booking_side_effects(engine) -> None:
    assert _booking_row_count(engine) == 0
    assert booking_store._bookings == []
    _assert_no_invalid_status_events(engine)


@pytest.fixture
def handler_edge_env(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'handlers-edge.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    recorder = OutboundRecorder()

    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(settings, "public_base_url", "https://example.test")
    monkeypatch.setattr(meta, "send_text", recorder.send_text)
    monkeypatch.setattr(meta, "send_buttons", recorder.send_buttons)
    monkeypatch.setattr(meta, "send_list", recorder.send_list)
    monkeypatch.setattr(meta, "send_template", recorder.send_template)
    monkeypatch.setattr(meta, "send_image_link", recorder.send_image_link)

    async def fake_notify_booking_confirmation(*args, **kwargs) -> dict:
        recorder.calls.append({"kind": "staff_notify", "args": args, "kwargs": kwargs})
        return {}

    monkeypatch.setattr(handlers, "notify_booking_confirmation", fake_notify_booking_confirmation)
    _configured_engine.cache_clear()
    state._sessions.clear()
    booking_store._bookings.clear()
    yield engine, recorder
    _configured_engine.cache_clear()
    state._sessions.clear()
    booking_store._bookings.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("state_name", DISPATCH_STATES)
async def test_dispatch_states_reprompt_unknown_button_payload_without_booking_write(
    handler_edge_env,
    state_name: str,
):
    engine, recorder = handler_edge_env
    phone = f"2126001{DISPATCH_STATES.index(state_name):04d}"
    _seed_session(phone, state_name)

    await handlers.handle_message(
        _interactive_message(
            phone,
            f"wamid.edge.unknown-button.{state_name}",
            "zzz_garbage",
        )
    )

    assert recorder.calls
    _assert_no_booking_side_effects(engine)


@pytest.mark.asyncio
@pytest.mark.parametrize("state_name", DISPATCH_STATES)
async def test_dispatch_states_reprompt_unknown_list_row_without_booking_write(
    handler_edge_env,
    state_name: str,
):
    engine, recorder = handler_edge_env
    phone = f"2126002{DISPATCH_STATES.index(state_name):04d}"
    _seed_session(phone, state_name)

    await handlers.handle_message(
        _interactive_message(
            phone,
            f"wamid.edge.unknown-list.{state_name}",
            "zzz_garbage",
            kind="list_reply",
        )
    )

    assert recorder.calls
    _assert_no_booking_side_effects(engine)


@pytest.mark.asyncio
@pytest.mark.parametrize("state_name", DISPATCH_STATES)
@pytest.mark.parametrize("case_name,text", TEXT_CORPUS, ids=[case[0] for case in TEXT_CORPUS])
async def test_dispatch_states_tolerate_adversarial_text_without_booking_write(
    handler_edge_env,
    state_name: str,
    case_name: str,
    text: str,
):
    engine, recorder = handler_edge_env
    phone = f"2126003{DISPATCH_STATES.index(state_name):04d}"
    _seed_session(phone, state_name)

    await handlers.handle_message(
        _text_message(phone, f"wamid.edge.text.{state_name}.{case_name}", text)
    )

    assert recorder.calls
    _assert_no_booking_side_effects(engine)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "shape",
    ("missing_reply_object", "missing_id", "empty_id", "unknown_interactive_type"),
)
@pytest.mark.parametrize("state_name", ("MENU", "BOOK_WHEN", "BOOK_CONFIRM", "UPSELL_DETAILING_PICK"))
async def test_malformed_interactive_payloads_do_not_escape_handler(
    handler_edge_env,
    state_name: str,
    shape: str,
):
    engine, recorder = handler_edge_env
    phone = f"2126004{DISPATCH_STATES.index(state_name):04d}"
    _seed_session(phone, state_name)

    await handlers.handle_message(
        _malformed_interactive_message(
            phone,
            f"wamid.edge.malformed.{state_name}.{shape}",
            shape,
        )
    )

    assert recorder.calls
    _assert_no_booking_side_effects(engine)


@pytest.mark.asyncio
async def test_returning_customer_reprompts_payload_outside_expected_buttons(handler_edge_env):
    engine, recorder = handler_edge_env
    phone = "212600500001"
    _seed_session(phone, "RETURNING_CUSTOMER")

    await handlers.handle_message(
        _interactive_message(
            phone,
            "wamid.edge.returning.bogus",
            "RETURNING_CUSTOMER:bogus",
        )
    )

    assert recorder.calls[-1]["kind"] == "buttons"
    button_ids = [button_id for button_id, _label in recorder.calls[-1]["buttons"]]
    assert button_ids == ["returning_yes", "returning_no", "returning_menu"]
    _assert_no_booking_side_effects(engine)


@pytest.mark.asyncio
async def test_stale_session_resets_before_dispatching_payload(handler_edge_env):
    engine, recorder = handler_edge_env
    phone = "212600500002"
    _seed_session(phone, "BOOK_MODEL", expired=True)

    await handlers.handle_message(
        _text_message(phone, "wamid.edge.stale.model", "Peugeot 208")
    )

    assert state.get(phone).state == "MENU"
    assert recorder.calls[-1]["kind"] == "buttons"
    _assert_no_booking_side_effects(engine)


@pytest.mark.asyncio
async def test_stale_book_confirm_with_past_slot_resets_without_booking(handler_edge_env):
    engine, recorder = handler_edge_env
    phone = "212600500003"
    past_booking = _complete_booking(phone, appointment_date=date.today() - timedelta(days=1))
    _seed_session(phone, "BOOK_CONFIRM", booking=past_booking, expired=True)

    await handlers.handle_message(
        _interactive_message(
            phone,
            "wamid.edge.stale-confirm.past-slot",
            "confirm_yes",
        )
    )

    assert state.get(phone).state == "MENU"
    assert recorder.calls[-1]["kind"] == "buttons"
    _assert_no_booking_side_effects(engine)


@pytest.mark.asyncio
async def test_mid_flow_phone_change_does_not_reuse_existing_session(handler_edge_env):
    engine, recorder = handler_edge_env
    original_phone = "212600500004"
    changed_phone = "212600500005"
    original = _seed_session(original_phone, "BOOK_COLOR")
    original_booking = original.booking

    await handlers.handle_message(
        _text_message(changed_phone, "wamid.edge.phone-change", "Noir")
    )

    assert state.get(original_phone).state == "BOOK_COLOR"
    assert state.get(original_phone).booking is original_booking
    assert state.get(changed_phone).state == "MENU"
    assert recorder.calls[-1]["to"] == changed_phone
    _assert_no_booking_side_effects(engine)
