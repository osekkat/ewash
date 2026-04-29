import pytest

from app import handlers, meta, state
from app.booking import Booking


@pytest.mark.asyncio
async def test_addon_saved_message_includes_full_updated_recap(monkeypatch):
    phone = "212665883062"
    booking = Booking(
        phone=phone,
        name="Oussama",
        vehicle_type="B — Berline / SUV",
        category="B",
        car_model="Toyota RAV4",
        color="Noir",
        service="svc_cpl",
        service_label="Le Complet — 125 DH",
        price_dh=125,
        location_mode="home",
        address="49 rue Jean Jaurès, Casablanca",
        geo="Gauthier | 49 rue Jean Jaurès | 📍 33.59, -7.62",
        date_label="Demain 30/04/2026",
        slot="09h – 11h",
        note="Portail bleu",
        ref="EW-2026-0099",
    )
    sess = state.Session(state="UPSELL_DETAILING_PICK", booking=booking)
    sent_texts = []

    async def fake_send_text(to, body):
        sent_texts.append((to, body))
        return {"ok": True}

    monkeypatch.setattr(meta, "send_text", fake_send_text)
    monkeypatch.setattr(handlers, "persist_booking_addon", lambda *args, **kwargs: None)

    await handlers._handle_upsell_detailing_pick(phone, sess, payload_id="svc_pol")

    assert len(sent_texts) == 1
    to, body = sent_texts[0]
    assert to == phone
    assert "✅ *Add-on enregistré !*" in body
    assert "📋 *Récapitulatif" in body
    assert "👤 *Nom* : Oussama" in body
    assert "🚗 *Véhicule* : B — Berline / SUV — Toyota RAV4 (Noir)" in body
    assert "🧼 *Service* : Le Complet — 125 DH" in body
    assert "✨ *Esthétique (-10%)* : Le Polissage — 963 DH (-10%)" in body
    assert "💰 *Total indicatif* : 1088 DH" in body
    assert "📍 *Lieu* : 🏠 49 rue Jean Jaurès, Casablanca" in body
    assert "🗺️ *Géoloc.* : Gauthier | 49 rue Jean Jaurès | 📍 33.59, -7.62" in body
    assert "🗓️ *Date* : Demain 30/04/2026" in body
    assert "⏰ *Créneau* : 09h – 11h" in body
    assert "📞 *Téléphone* : +212665883062" in body
    assert "📝 *Note* : Portail bleu" in body
