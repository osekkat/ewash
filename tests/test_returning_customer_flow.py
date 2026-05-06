import pytest
from sqlalchemy import select

from app import handlers, meta, state
from app.booking import Booking
from app.config import settings
from app.db import init_db, make_engine, session_scope
from app.models import Customer, CustomerName, CustomerVehicle
from app.persistence import _configured_engine, get_returning_customer_profile, persist_booking_identity


def _interactive_message(phone: str, message_id: str, payload_id: str, *, kind: str = "button_reply") -> dict:
    return {
        "id": message_id,
        "from": phone,
        "type": "interactive",
        "interactive": {
            "type": kind,
            kind: {"id": payload_id, "title": payload_id},
        },
    }


def _text_message(phone: str, message_id: str, body: str) -> dict:
    return {"id": message_id, "from": phone, "type": "text", "text": {"body": body}}


def _seed_vehicle(engine, *, phone: str, name: str = "Hassan") -> None:
    booking = Booking(
        phone=phone,
        name=name,
        vehicle_type="B — Berline / SUV",
        category="B",
        car_model="Nissan Sentra",
        color="Jaune",
    )
    persist_booking_identity(booking, engine=engine)


@pytest.mark.asyncio
async def test_known_number_gets_returning_customer_prompt(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'returning-prompt.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    phone = "212600000201"
    _seed_vehicle(engine, phone=phone)
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    state.reset(phone)
    sent_buttons = []

    async def fake_send_buttons(to, body, buttons):
        sent_buttons.append((to, body, buttons))
        return {}

    monkeypatch.setattr(meta, "send_buttons", fake_send_buttons)

    await handlers.handle_message(_text_message(phone, "wamid.returning.prompt", "Bonjour"))

    assert sent_buttons
    assert sent_buttons[0][0] == phone
    assert "Bonjour Hassan, est-ce pour Nissan Sentra — Jaune ?" in sent_buttons[0][1]
    assert [button_id for button_id, _label in sent_buttons[0][2]] == [
        "returning_yes",
        "returning_no",
        "returning_menu",
    ]
    assert state.get(phone).state == "RETURNING_CUSTOMER"
    with session_scope(engine) as session:
        customer = session.get(Customer, phone)
        assert customer is not None
        assert customer.last_bot_stage == "RETURNING_CUSTOMER"
        assert customer.last_bot_stage_label == "Confirmation client connu"
    _configured_engine.cache_clear()


@pytest.mark.asyncio
async def test_returning_customer_yes_skips_name_and_vehicle_questions(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'returning-yes.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    phone = "212600000202"
    _seed_vehicle(engine, phone=phone)
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    state.reset(phone)
    sent_buttons = []

    async def fake_send_buttons(to, body, buttons):
        sent_buttons.append((to, body, buttons))
        return {}

    monkeypatch.setattr(meta, "send_buttons", fake_send_buttons)

    await handlers.handle_message(_text_message(phone, "wamid.returning.yes.1", "Bonjour"))
    await handlers.handle_message(_interactive_message(phone, "wamid.returning.yes.2", "returning_yes"))

    sess = state.get(phone)
    assert sess.state == "BOOK_WHERE"
    assert sess.booking.name == "Hassan"
    assert sess.booking.category == "B"
    assert sess.booking.vehicle_type == "B — Berline / SUV"
    assert sess.booking.car_model == "Nissan Sentra"
    assert sess.booking.color == "Jaune"
    assert any("Où souhaitez-vous le lavage ?" in body for _to, body, _buttons in sent_buttons)
    _configured_engine.cache_clear()


@pytest.mark.asyncio
async def test_returning_customer_no_stores_new_name_and_new_car(monkeypatch, tmp_path):
    db_url = f"sqlite+pysqlite:///{tmp_path / 'returning-no.db'}"
    engine = make_engine(db_url)
    init_db(engine)
    phone = "212600000203"
    _seed_vehicle(engine, phone=phone, name="Hassan")
    monkeypatch.setattr(settings, "database_url", db_url)
    _configured_engine.cache_clear()
    state.reset(phone)
    sent_texts = []

    async def fake_send_buttons(*args, **kwargs):
        return {}

    async def fake_send_text(to, body):
        sent_texts.append((to, body))
        return {}

    async def fake_send_list(*args, **kwargs):
        return {}

    monkeypatch.setattr(meta, "send_buttons", fake_send_buttons)
    monkeypatch.setattr(meta, "send_text", fake_send_text)
    monkeypatch.setattr(meta, "send_list", fake_send_list)

    await handlers.handle_message(_text_message(phone, "wamid.returning.no.1", "Bonjour"))
    await handlers.handle_message(_interactive_message(phone, "wamid.returning.no.2", "returning_no"))
    await handlers.handle_message(_text_message(phone, "wamid.returning.no.3", "Youssef"))
    await handlers.handle_message(_interactive_message(phone, "wamid.returning.no.4", "veh_a", kind="list_reply"))
    await handlers.handle_message(_text_message(phone, "wamid.returning.no.5", "Peugeot 208"))
    await handlers.handle_message(_text_message(phone, "wamid.returning.no.6", "Bleu"))

    assert any("Comment vous appelez-vous ?" in body for _to, body in sent_texts)
    assert state.get(phone).state == "BOOK_WHERE"
    with session_scope(engine) as session:
        names = session.scalars(select(CustomerName).where(CustomerName.customer_phone == phone)).all()
        vehicles = session.scalars(
            select(CustomerVehicle).where(CustomerVehicle.customer_phone == phone).order_by(CustomerVehicle.last_used_at)
        ).all()
        assert sorted(name.display_name for name in names) == ["Hassan", "Youssef"]
        assert sorted(vehicle.label for vehicle in vehicles) == ["Nissan Sentra — Jaune", "Peugeot 208 — Bleu"]
        assert all(vehicle.last_used_at is not None for vehicle in vehicles)

    profile = get_returning_customer_profile(phone, engine=engine)
    assert profile is not None
    assert profile.display_name == "Youssef"
    assert profile.vehicle_label == "Peugeot 208 — Bleu"
    _configured_engine.cache_clear()
