"""Meta Cloud API client — signature verification + outbound send.

Supports:
- send_text:      plain free-form message
- send_buttons:   up to 3 reply buttons
- send_list:      up to 10 options in a dropdown (grouped in sections)
- Inbound parsers for button_reply, list_reply, location pins
"""
import hashlib
import hmac
import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)

GRAPH_API_URL = (
    f"https://graph.facebook.com/v21.0/{settings.meta_phone_number_id}/messages"
)


def verify_signature(payload: bytes, signature_header: str | None) -> bool:
    """Validate Meta's X-Hub-Signature-256 using the App Secret."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = signature_header.removeprefix("sha256=")
    digest = hmac.new(
        settings.meta_app_secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, digest)


async def _post(payload: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {settings.meta_access_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(GRAPH_API_URL, headers=headers, json=payload)
    if r.status_code >= 400:
        log.error("Meta send failed status=%s body=%s", r.status_code, r.text)
    r.raise_for_status()
    return r.json()


async def send_text(to: str, body: str) -> dict:
    """Free-form text message. Only valid inside the 24h session window."""
    return await _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": body},
    })


async def send_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> dict:
    """Send up to 3 quick-reply buttons.

    buttons: list of (button_id, label). label <= 20 chars.
    """
    if len(buttons) > 3:
        raise ValueError("WhatsApp supports max 3 reply buttons")
    return await _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": bid, "title": label[:20]},
                    }
                    for bid, label in buttons
                ]
            },
        },
    })


async def send_list(
    to: str,
    body: str,
    button_label: str,
    rows: list[tuple[str, str, str]],
    section_title: str = "Options",
) -> dict:
    """Send a list message (dropdown). Up to 10 rows total.

    rows: list of (row_id, title, description). title <= 24 chars, description <= 72.
    """
    if len(rows) > 10:
        raise ValueError("WhatsApp supports max 10 list rows")
    return await _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": button_label[:20],
                "sections": [
                    {
                        "title": section_title[:24],
                        "rows": [
                            {
                                "id": rid,
                                "title": title[:24],
                                "description": (desc or "")[:72],
                            }
                            for rid, title, desc in rows
                        ],
                    }
                ],
            },
        },
    })


# ── inbound parsers ─────────────────────────────────────────────────────────
def extract_interactive_id(message: dict) -> str | None:
    """Return the id of a tapped button or list row, if any."""
    if message.get("type") != "interactive":
        return None
    inter = message.get("interactive", {})
    kind = inter.get("type")
    if kind == "button_reply":
        return inter.get("button_reply", {}).get("id")
    if kind == "list_reply":
        return inter.get("list_reply", {}).get("id")
    return None


def extract_text(message: dict) -> str | None:
    """Return the body text of a plain text message, if any."""
    if message.get("type") == "text":
        return message.get("text", {}).get("body")
    return None


def extract_location(message: dict) -> dict | None:
    """Return {latitude, longitude, name, address} if message is a location pin."""
    if message.get("type") == "location":
        return message.get("location", {})
    return None
