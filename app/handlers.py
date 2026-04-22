"""Inbound WhatsApp dispatcher — button/list-driven booking flow.

Entry: handle_message(message, contact) is called for each inbound message.
We advance the per-phone state machine and send the next prompt.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from . import catalog, meta, state
from .booking import Booking

log = logging.getLogger(__name__)

# Locale-independent French weekday names. Railway's Linux container defaults
# to the C locale, so strftime("%A") would yield English ("Wednesday" etc.).
_JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _jour_fr(d: date) -> str:
    """Return the capitalized French weekday name for a date (e.g. 'Mercredi')."""
    return _JOURS_FR[d.weekday()].capitalize()


# ── Top-level entry ────────────────────────────────────────────────────────
async def handle_message(message: dict, contact: dict | None = None) -> None:
    phone = message.get("from")
    if not phone:
        return

    payload_id = meta.extract_interactive_id(message)
    text = meta.extract_text(message)
    location = meta.extract_location(message)

    sess = state.get(phone)
    log.info("inbound phone=%s state=%s payload=%s text=%r",
             phone, sess.state, payload_id, text)

    # Global escape hatches (work in any state)
    if text and text.strip().lower() in {"reset", "annuler", "cancel", "/reset"}:
        state.reset(phone)
        await _send_menu(phone, greeting="Conversation réinitialisée.")
        return
    if text and text.strip().lower() in {"menu", "start", "bonjour", "salam", "hi", "hello"}:
        state.reset(phone)
        await _send_menu(phone)
        return

    # Dispatch on state
    handler = _DISPATCH.get(sess.state, _handle_idle)
    await handler(phone, sess, payload_id=payload_id, text=text, location=location,
                  contact=contact)


# ── Individual state handlers ──────────────────────────────────────────────
async def _handle_idle(phone, sess, **kw):
    # Anything in IDLE → show the welcome menu.
    await _send_menu(phone)


async def _handle_menu(phone, sess, payload_id=None, text=None, **kw):
    if payload_id == "menu_book":
        state.start_booking(phone)
        await meta.send_text(phone, "Parfait ! 📝\n\nComment vous appelez-vous ?")
        return
    if payload_id == "menu_services":
        await _show_services_info(phone)
        await _send_menu(phone, greeting="Autre chose ?")
        return
    if payload_id == "menu_human":
        sess.state = "HANDOFF"
        await meta.send_text(
            phone,
            "👋 Écrivez votre message ci-dessous et un membre de l'équipe Ewash "
            "vous recontactera très rapidement.",
        )
        return
    # Unknown → re-prompt
    await _send_menu(phone, greeting="Je n'ai pas compris. Choisissez une option :")


async def _handle_handoff(phone, sess, text=None, **kw):
    # Log a handoff request — in v0.3 we'll notify Omar on his WhatsApp.
    if text:
        log.warning("HANDOFF REQUEST phone=%s text=%r", phone, text)
        await meta.send_text(
            phone,
            "✅ Merci ! Votre message a bien été transmis à l'équipe Ewash. "
            "Nous vous recontacterons dès que possible.",
        )
        state.reset(phone)
    else:
        await meta.send_text(phone, "Merci d'écrire votre message en texte.")


async def _handle_book_name(phone, sess, text=None, **kw):
    if not text or len(text.strip()) < 2:
        await meta.send_text(phone, "Pouvez-vous me donner votre nom ?")
        return
    sess.booking.name = text.strip()[:60]
    sess.state = "BOOK_VEHICLE"
    await meta.send_list(
        phone,
        f"Merci {sess.booking.name} 👋\n\nQuel type de véhicule ?",
        button_label="Choisir le véhicule",
        rows=catalog.VEHICLE_CATEGORIES,
        section_title="Catégories",
    )


async def _handle_book_vehicle(phone, sess, payload_id=None, **kw):
    if payload_id not in catalog.VEHICLE_CATEGORY_KEY:
        await meta.send_list(
            phone, "Choisissez le type de véhicule :",
            "Choisir le véhicule",
            catalog.VEHICLE_CATEGORIES, "Catégories",
        )
        return
    sess.booking.vehicle_type = catalog.label_for(catalog.VEHICLE_CATEGORIES, payload_id)
    sess.booking.category = catalog.VEHICLE_CATEGORY_KEY[payload_id]

    # Moto lane skips model/color questions — straight to service list.
    if sess.booking.category == "MOTO":
        sess.state = "BOOK_SERVICE"
        await meta.send_list(
            phone,
            "Quel type de lavage ?",
            button_label="Voir les tarifs",
            rows=catalog.build_moto_service_rows(),
            section_title="Tarifs moto",
        )
        return

    sess.state = "BOOK_MODEL"
    await meta.send_text(
        phone,
        "Quelle est la marque et le modèle ? (ex: *Dacia Logan*, *Toyota RAV4*)",
    )


async def _handle_book_model(phone, sess, text=None, **kw):
    if not text or len(text.strip()) < 2:
        await meta.send_text(phone, "Indiquez la marque et le modèle, svp.")
        return
    sess.booking.car_model = text.strip()[:60]
    sess.state = "BOOK_COLOR"
    await meta.send_text(
        phone,
        "Quelle est la *couleur* du véhicule ? (ex: *Blanc*, *Gris métallisé*, *Rouge bordeaux*)",
    )


async def _handle_book_color(phone, sess, payload_id=None, text=None, **kw):
    if text and text.strip():
        sess.booking.color = text.strip()[:30]
    else:
        await meta.send_text(
            phone,
            "Merci d'indiquer la couleur du véhicule (ex: *Blanc*, *Gris*, *Bleu nuit*).",
        )
        return
    # Cars go straight to the Lavages catalog. Esthétique is offered as a -10%
    # upsell after the booking is confirmed (see _handle_book_confirm).
    sess.booking.service_bucket = "wash"
    sess.state = "BOOK_SERVICE"
    cat = sess.booking.category
    await meta.send_list(
        phone,
        f"🧼 *Nos formules de lavage*\n_(tarifs pour catégorie {cat})_",
        button_label="Voir les tarifs",
        rows=catalog.build_car_service_rows(cat, bucket="wash"),
        section_title=f"Lavages · cat. {cat}",
    )


async def _handle_book_service(phone, sess, payload_id=None, **kw):
    cat = sess.booking.category
    # Valid service IDs depend on the lane:
    #   - moto → SERVICES_MOTO
    #   - car  → SERVICES_WASH (bucket is pre-set to "wash" in _handle_book_color;
    #           Esthétique is handled separately via the post-confirmation upsell).
    if cat == "MOTO":
        valid = {sid for sid, *_ in catalog.SERVICES_MOTO}
        rows = catalog.build_moto_service_rows()
        section = "Tarifs moto"
        body = "Choisissez un service :"
    else:
        bucket = sess.booking.service_bucket or "all"
        if bucket == "wash":
            valid = {sid for sid, *_ in catalog.SERVICES_WASH}
            section = f"Lavages · cat. {cat}"
            body = f"🧼 *Nos formules de lavage*\n_(cat. {cat})_"
        elif bucket == "detailing":
            valid = {sid for sid, *_ in catalog.SERVICES_DETAILING}
            section = f"Esthétique · cat. {cat}"
            body = f"✨ *Nos offres d'esthétique*\n_(cat. {cat})_"
        else:
            valid = {sid for sid, *_ in catalog.SERVICES_CAR}
            section = f"Tarifs catégorie {cat}"
            body = f"Choisissez un service :\n_(cat. {cat})_"
        rows = catalog.build_car_service_rows(cat, bucket=bucket)

    if payload_id not in valid:
        await meta.send_list(phone, body, "Voir les tarifs", rows, section)
        return

    price = catalog.service_price(payload_id, cat)
    name = catalog.service_name(payload_id)
    sess.booking.service = payload_id
    sess.booking.service_label = f"{name} — {price} DH"
    sess.booking.price_dh = price or 0
    sess.state = "BOOK_WHERE"
    await meta.send_buttons(
        phone,
        "Où souhaitez-vous le lavage ?\n\n"
        "🚗 *Service à domicile* — Casablanca, sur RDV\n"
        "📍 *Stand physique* — Mall Triangle Vert, Bouskoura | 7j/7 · 09h-22h30",
        [("where_home",   "🚗 À domicile"),
         ("where_center", "📍 Au stand")],
    )


async def _handle_book_where(phone, sess, payload_id=None, **kw):
    if payload_id == "where_center":
        sess.booking.location_mode = "center"
        if len(catalog.CENTERS) == 1:
            # Only one center → auto-pick and skip selection.
            row = catalog.CENTERS[0]
            sess.booking.center = f"{row[1]} — {row[2]}"
            await _ask_when(phone, sess)
        else:
            sess.state = "BOOK_CENTER"
            await meta.send_list(phone, "Quel centre Ewash ?", "Choisir le centre",
                                 catalog.CENTERS, "Centres disponibles")
        return
    if payload_id == "where_home":
        sess.booking.location_mode = "home"
        sess.state = "BOOK_GEO"
        await meta.send_text(
            phone,
            "📍 *Partagez votre localisation*\n\n"
            "Appuyez sur *+* → *Position* (ou *Location*) puis "
            "*Envoyer ma position actuelle*, ou épinglez un lieu sur la carte.",
        )
        return
    await meta.send_buttons(
        phone,
        "Choisissez un lieu :\n\n"
        "🚗 *Service à domicile* — Casablanca, sur RDV\n"
        "📍 *Stand physique* — Mall Triangle Vert, Bouskoura | 7j/7 · 09h-22h30",
        [("where_home",   "🚗 À domicile"),
         ("where_center", "📍 Au stand")],
    )


async def _handle_book_center(phone, sess, payload_id=None, **kw):
    if payload_id not in {row[0] for row in catalog.CENTERS}:
        await meta.send_list(phone, "Choisissez un centre :", "Choisir le centre",
                             catalog.CENTERS, "Centres disponibles")
        return
    sess.booking.center = catalog.label_for(catalog.CENTERS, payload_id)
    await _ask_when(phone, sess)


async def _handle_book_geo(phone, sess, location=None, **kw):
    if not location:
        await meta.send_text(
            phone,
            "Je n'ai pas reçu de position 📍\n\n"
            "Appuyez sur *+* → *Position* puis *Envoyer ma position actuelle*, "
            "ou épinglez un lieu sur la carte.",
        )
        return
    parts = []
    if location.get("name"):
        parts.append(location["name"])
    if location.get("address"):
        parts.append(location["address"])
    parts.append(f"📍 {location.get('latitude')}, {location.get('longitude')}")
    sess.booking.geo = " | ".join(parts)
    sess.state = "BOOK_ADDRESS"
    await meta.send_text(
        phone,
        "Merci 🙏\n\nIndiquez maintenant votre *adresse* et toute information utile "
        "pour vous trouver (nom d'immeuble/villa, place de parking, repères…).",
    )


async def _handle_book_address(phone, sess, text=None, **kw):
    if not text or len(text.strip()) < 5:
        await meta.send_text(
            phone,
            "Pouvez-vous me donner plus de détails en texte ? "
            "Adresse précise + infos d'accès (immeuble, étage, code, repères…).",
        )
        return
    sess.booking.address = text.strip()[:300]
    await _ask_when(phone, sess)


async def _ask_when(phone, sess):
    sess.state = "BOOK_WHEN"
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(6)]
    rows = [
        ("when_today",    "Aujourd'hui",  dates[0].strftime("%d/%m/%Y")),
        ("when_tomorrow", "Demain",       dates[1].strftime("%d/%m/%Y")),
        ("when_plus2",    f"{_jour_fr(dates[2])} {dates[2].strftime('%d/%m')}", ""),
        ("when_plus3",    f"{_jour_fr(dates[3])} {dates[3].strftime('%d/%m')}", ""),
        ("when_plus4",    f"{_jour_fr(dates[4])} {dates[4].strftime('%d/%m')}", ""),
        ("when_plus5",    f"{_jour_fr(dates[5])} {dates[5].strftime('%d/%m')}", ""),
    ]
    await meta.send_list(phone, "Quel jour ?", "Choisir la date", rows, "Dates disponibles")


async def _handle_book_when(phone, sess, payload_id=None, **kw):
    mapping = {
        "when_today":    ("Aujourd'hui",  0),
        "when_tomorrow": ("Demain",        1),
        "when_plus2":    ("",              2),
        "when_plus3":    ("",              3),
        "when_plus4":    ("",              4),
        "when_plus5":    ("",              5),
    }
    if payload_id not in mapping:
        await _ask_when(phone, sess)
        return
    label, delta = mapping[payload_id]
    d = date.today() + timedelta(days=delta)
    sess.booking.date_label = label or f"{_jour_fr(d)} {d.strftime('%d/%m/%Y')}"
    sess.state = "BOOK_SLOT"
    await meta.send_list(phone, "À quelle heure ?", "Choisir un créneau",
                         catalog.SLOTS, "Créneaux")


async def _handle_book_slot(phone, sess, payload_id=None, **kw):
    if payload_id not in {row[0] for row in catalog.SLOTS}:
        await meta.send_list(phone, "Choisissez un créneau :", "Choisir un créneau",
                             catalog.SLOTS, "Créneaux")
        return
    sess.booking.slot = catalog.label_for(catalog.SLOTS, payload_id)
    sess.state = "BOOK_NOTE"
    await meta.send_buttons(
        phone,
        "Souhaitez-vous ajouter une note (tâches particulières, instructions d'accès…) ?",
        [("note_skip", "Non, passer"), ("note_add", "Ajouter une note")],
    )


async def _handle_book_note(phone, sess, payload_id=None, **kw):
    if payload_id == "note_skip":
        await _send_recap(phone, sess)
        return
    if payload_id == "note_add":
        sess.state = "BOOK_NOTE_TEXT"
        await meta.send_text(phone, "✍️ Écrivez votre note :")
        return
    await meta.send_buttons(
        phone, "Souhaitez-vous ajouter une note ?",
        [("note_skip", "Non, passer"), ("note_add", "Ajouter une note")],
    )


async def _handle_book_note_text(phone, sess, text=None, **kw):
    if not text:
        await meta.send_text(phone, "Merci d'écrire votre note en texte.")
        return
    sess.booking.note = text.strip()[:300]
    await _send_recap(phone, sess)


async def _send_recap(phone, sess):
    b = sess.booking
    if b.location_mode == "center":
        where_block = f"📍 *Lieu* : 🏢 {b.center}\n"
    else:
        where_block = f"📍 *Lieu* : 🏠 {b.address}\n"
        if b.geo:
            where_block += f"🗺️ *Géoloc.* : {b.geo}\n"
    # Moto lane skips model/color — render vehicle line accordingly.
    if b.category == "MOTO":
        vehicle_line = f"🏍️ *Véhicule* : {b.vehicle_type}\n"
    else:
        vehicle_line = f"🚗 *Véhicule* : {b.vehicle_type} — {b.car_model} ({b.color})\n"
    recap = (
        "📋 *Récapitulatif*\n\n"
        f"👤 *Nom* : {b.name}\n"
        + vehicle_line +
        f"🧼 *Service* : {b.service_label or b.service}\n"
        + where_block +
        f"🗓️ *Date* : {b.date_label}\n"
        f"⏰ *Créneau* : {b.slot}\n"
        f"📞 *Téléphone* : +{b.phone}\n"
    )
    if b.note:
        recap += f"📝 *Note* : {b.note}\n"
    recap += (
        "\n_Le tarif affiché est indicatif — l'équipe confirme selon l'état "
        "du véhicule._\n\nTout est correct ?"
    )
    sess.state = "BOOK_CONFIRM"
    await meta.send_buttons(
        phone, recap,
        [("confirm_yes", "✅ Confirmer"),
         ("confirm_edit", "✏️ Modifier"),
         ("confirm_no",  "❌ Annuler")],
    )


async def _handle_book_confirm(phone, sess, payload_id=None, **kw):
    if payload_id == "confirm_yes":
        ref = sess.booking.assign_ref()
        await meta.send_text(
            phone,
            f"✅ *Réservation enregistrée !*\n\n"
            f"Référence : *{ref}*\n\n"
            f"L'équipe Ewash vous contactera très prochainement pour confirmer "
            f"le créneau et le tarif. Merci de votre confiance ! 🙏",
        )
        # Moto customers have no Esthétique catalog — skip the upsell and end here.
        if sess.booking.category == "MOTO":
            state.reset(phone)
            return
        sess.state = "UPSELL_DETAILING"
        await meta.send_buttons(
            phone,
            "🎁 *Offre du jour*\n\nAjoutez une prestation d'*Esthétique* à votre "
            "rendez-vous et profitez de *-10%* — aujourd'hui seulement.",
            [("upsell_yes", "✨ Voir l'offre"),
             ("upsell_no",  "Non merci")],
        )
        return
    if payload_id == "confirm_edit":
        # Simple approach: restart the flow, keeping the phone as key.
        state.start_booking(phone)
        await meta.send_text(phone,
            "Reprenons 🙂\n\nComment vous appelez-vous ?")
        return
    if payload_id == "confirm_no":
        state.reset(phone)
        await meta.send_text(phone,
            "Réservation annulée. Envoyez *menu* pour recommencer à tout moment.")
        return
    # Unknown payload — re-show recap
    await _send_recap(phone, sess)


def _build_detailing_upsell_rows(category: str) -> list[tuple[str, str, str]]:
    """Render SERVICES_DETAILING as WhatsApp list rows with prices already
    discounted by 10% (rounded to nearest DH)."""
    rows = []
    for sid, name, desc, prices in catalog.SERVICES_DETAILING:
        base = prices.get(category)
        if base is None:
            continue
        disc = round(base * 0.9)
        title = f"{name} — {disc} DH"
        rows.append((sid, title[:24], desc[:72]))
    return rows


async def _handle_upsell_detailing(phone, sess, payload_id=None, **kw):
    if payload_id == "upsell_yes":
        cat = sess.booking.category
        sess.state = "UPSELL_DETAILING_PICK"
        await meta.send_list(
            phone,
            f"✨ *Esthétique à -10%*\n_(remise déjà appliquée, catégorie {cat})_",
            button_label="Choisir prestation",
            rows=_build_detailing_upsell_rows(cat),
            section_title=f"Esthétique -10% · cat. {cat}",
        )
        return
    if payload_id == "upsell_no":
        await meta.send_text(phone, "Parfait, à très vite chez Ewash ! 🙂")
        state.reset(phone)
        return
    # Unknown → re-prompt
    await meta.send_buttons(
        phone,
        "Souhaitez-vous ajouter l'Esthétique à -10% ?",
        [("upsell_yes", "✨ Voir l'offre"), ("upsell_no", "Non merci")],
    )


async def _handle_upsell_detailing_pick(phone, sess, payload_id=None, **kw):
    cat = sess.booking.category
    valid = {sid for sid, *_ in catalog.SERVICES_DETAILING}
    if payload_id not in valid:
        await meta.send_list(
            phone,
            f"✨ *Esthétique à -10%*\n_(remise déjà appliquée, catégorie {cat})_",
            "Choisir la prestation",
            _build_detailing_upsell_rows(cat),
            f"Esthétique -10% · cat. {cat}",
        )
        return
    base = catalog.service_price(payload_id, cat)
    disc = round(base * 0.9) if base is not None else 0
    name = catalog.service_name(payload_id)
    label = f"{name} — {disc} DH (-10%)"
    sess.booking.addon_service = payload_id
    sess.booking.addon_service_label = label
    sess.booking.addon_price_dh = disc
    from .booking import update_booking
    update_booking(
        sess.booking.ref,
        addon_service=payload_id,
        addon_service_label=label,
        addon_price_dh=disc,
    )
    main = sess.booking.service_label or sess.booking.service or "—"
    total = (sess.booking.price_dh or 0) + disc
    await meta.send_text(
        phone,
        f"✅ *Add-on enregistré !*\n\n"
        f"Votre réservation *{sess.booking.ref}* a bien été mise à jour :\n\n"
        f"🧼 *Lavage* : {main}\n"
        f"✨ *Esthétique (-10%)* : {label}\n"
        f"💰 *Total indicatif* : {total} DH\n\n"
        f"_Le tarif reste indicatif — l'équipe confirme selon l'état du véhicule._\n\n"
        f"L'équipe Ewash confirmera lors de l'intervention. À très vite ! 🙏",
    )
    state.reset(phone)


# ── Helpers ─────────────────────────────────────────────────────────────────
async def _send_menu(phone: str, greeting: str | None = None) -> None:
    state.reset(phone)
    sess = state.get(phone)
    sess.state = "MENU"
    body = (greeting + "\n\n" if greeting else
            "👋 *Bienvenue chez Ewash* — lavage auto écologique sans eau.\n\n")
    body += "Que souhaitez-vous faire ?"
    await meta.send_buttons(
        phone, body,
        [("menu_book",     "📅 Prendre RDV"),
         ("menu_services", "🧼 Nos services"),
         ("menu_human",    "💬 Parler à l'équipe")],
    )


async def _show_services_info(phone: str) -> None:
    lines = ["*🧼 Nos services Ewash* _(tarifs A/B/C en DH)_:\n"]
    for _id, name, desc, prices in catalog.SERVICES_CAR:
        price_str = f"{prices['A']}/{prices['B']}/{prices['C']} DH"
        lines.append(f"• *{name}* — {price_str}\n  _{desc}_")
    lines.append("")
    lines.append("*🏍️ Moto* :")
    for _id, name, desc, price in catalog.SERVICES_MOTO:
        lines.append(f"• *{name}* — {price} DH  _{desc}_")
    lines.append("")
    lines.append("*Catégories de véhicule* :")
    lines.append("A = Citadine · B = Berline/SUV moyen · C = Grande berline/SUV")
    await meta.send_text(phone, "\n".join(lines))


# ── Dispatch table ─────────────────────────────────────────────────────────
_DISPATCH = {
    "IDLE":                  _handle_idle,
    "MENU":                  _handle_menu,
    "HANDOFF":               _handle_handoff,
    "BOOK_NAME":             _handle_book_name,
    "BOOK_VEHICLE":          _handle_book_vehicle,
    "BOOK_MODEL":            _handle_book_model,
    "BOOK_COLOR":            _handle_book_color,
    "BOOK_SERVICE":          _handle_book_service,
    "BOOK_WHERE":            _handle_book_where,
    "BOOK_CENTER":           _handle_book_center,
    "BOOK_GEO":              _handle_book_geo,
    "BOOK_ADDRESS":          _handle_book_address,
    "BOOK_WHEN":             _handle_book_when,
    "BOOK_SLOT":             _handle_book_slot,
    "BOOK_NOTE":             _handle_book_note,
    "BOOK_NOTE_TEXT":        _handle_book_note_text,
    "BOOK_CONFIRM":          _handle_book_confirm,
    "UPSELL_DETAILING":      _handle_upsell_detailing,
    "UPSELL_DETAILING_PICK": _handle_upsell_detailing_pick,
}
