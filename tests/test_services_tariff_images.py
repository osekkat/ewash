import pytest

from app import handlers, meta
from app.config import settings


@pytest.mark.asyncio
async def test_show_services_info_sends_tariff_images_instead_of_long_text(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://ewash.example")
    sent_images = []

    async def fake_send_image_link(to, image_url, caption=None):
        sent_images.append((to, image_url, caption))
        return {"ok": True}

    async def fail_send_text(to, body):
        raise AssertionError("Nos services should send tariff flyer images, not the long text catalog")

    monkeypatch.setattr(meta, "send_image_link", fake_send_image_link)
    monkeypatch.setattr(meta, "send_text", fail_send_text)

    await handlers._show_services_info("212665883062")

    assert sent_images == [
        (
            "212665883062",
            "https://ewash.example/static/tarifs-lavage.jpg",
            "🧼 Tarifs Ewash — lavage auto",
        ),
        (
            "212665883062",
            "https://ewash.example/static/tarifs-esthetique.jpg",
            "✨ Tarifs Ewash — esthétique & protections",
        ),
    ]


@pytest.mark.asyncio
async def test_send_image_link_posts_whatsapp_image_payload(monkeypatch):
    payloads = []

    async def fake_post(payload):
        payloads.append(payload)
        return {"messages": [{"id": "wamid.test"}]}

    monkeypatch.setattr(meta, "_post", fake_post)

    result = await meta.send_image_link(
        "212665883062",
        "https://ewash.example/static/tarifs-lavage.jpg",
        caption="🧼 Tarifs Ewash",
    )

    assert result == {"messages": [{"id": "wamid.test"}]}
    assert payloads == [
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": "212665883062",
            "type": "image",
            "image": {
                "link": "https://ewash.example/static/tarifs-lavage.jpg",
                "caption": "🧼 Tarifs Ewash",
            },
        }
    ]


@pytest.mark.asyncio
async def test_send_template_posts_whatsapp_template_payload(monkeypatch):
    payloads = []

    async def fake_post(payload):
        payloads.append(payload)
        return {"messages": [{"id": "wamid.template"}]}

    monkeypatch.setattr(meta, "_post", fake_post)

    result = await meta.send_template(
        "212665883062",
        "new_booking_alert",
        language_code="fr",
        body_parameters=["Nouvelle reservation", "EW-2026-0001"],
    )

    assert result == {"messages": [{"id": "wamid.template"}]}
    assert payloads == [
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": "212665883062",
            "type": "template",
            "template": {
                "name": "new_booking_alert",
                "language": {"code": "fr"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": "Nouvelle reservation"},
                            {"type": "text", "text": "EW-2026-0001"},
                        ],
                    }
                ],
            },
        }
    ]
