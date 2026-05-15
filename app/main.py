"""Ewash WhatsApp agent — Meta Cloud API webhook receiver.

Endpoints:
  GET  /health    → liveness probe for Railway
  GET  /webhook   → Meta webhook verification challenge
  POST /webhook   → Inbound customer messages (signature-verified)
"""
import logging
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import admin, handlers, meta
from .config import settings
from .persistence import mark_abandoned_conversations

APP_VERSION = "v0.3.0-alpha17"
STATIC_DIR = Path(__file__).resolve().parent / "static"

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("ewash")

app = FastAPI(title="Ewash WhatsApp Agent", version=APP_VERSION.removeprefix("v"))
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}


@app.post("/internal/conversations/abandon")
async def abandon_stale_conversations(
    x_internal_cron_secret: str | None = Header(default=None, alias="X-Internal-Cron-Secret"),
):
    """Protected maintenance hook for marking inactive conversation sessions abandoned."""
    if not settings.internal_cron_secret:
        raise HTTPException(status_code=503, detail="Internal cron is not configured")
    if x_internal_cron_secret != settings.internal_cron_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    count = mark_abandoned_conversations()
    return {"abandoned": count}


@app.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(request: Request):
    params = request.query_params
    if (params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token") == settings.meta_verify_token):
        log.info("webhook verified OK")
        return PlainTextResponse(content=params.get("hub.challenge") or "", status_code=200)
    log.warning("webhook verification failed mode=%s", params.get("hub.mode"))
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def receive_webhook(request: Request):
    raw = await request.body()
    if not meta.verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        log.warning("invalid signature, rejecting")
        raise HTTPException(status_code=403, detail="Bad signature")

    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", []) or []
            contacts = value.get("contacts", []) or []
            for i, msg in enumerate(messages):
                contact = contacts[i] if i < len(contacts) else None
                try:
                    await handlers.handle_message(msg, contact)
                except Exception:
                    log.exception("handler error msg_id=%s", msg.get("id"))

    # Always 200 fast — Meta retries on non-2xx.
    return Response(status_code=200)
